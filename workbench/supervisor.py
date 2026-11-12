"""Keep the browser control surface available when the research service is down."""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .accounts import COOKIE_NAME, SESSION_SECONDS, AccountError, Accounts
from .connection_context import HEADER, PROXY_KEYS
from .connection_proxy import Connections

WEB_ROOT = Path(__file__).resolve().parent / "web"


class Service:
    def __init__(self, workspace: Path, data_dir: Path, *, isolated: bool = False, connections=None):
        self.workspace, self.data_dir = workspace.resolve(), data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "service_settings.json"
        self.settings = (
            json.loads(self.settings_path.read_text()) if self.settings_path.is_file() else {}
        )
        self.log_path = self.workspace / "assets/logs/workbench/service.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.restarting = False
        self.message = "服务准备启动。"
        self.isolated = isolated
        self.worker_token = secrets.token_urlsafe(32)
        self.closed = False
        self.connections = connections

    def start(self) -> None:
        with self.lock:
            if self.closed:
                return
            if self.process and self.process.poll() is None:
                return
            if self.settings_path.is_file():
                self.settings = json.loads(self.settings_path.read_text())
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                self.port = sock.getsockname()[1]
            env = {**os.environ, **self.settings}
            if self.connections is not None and self.connections.enabled:
                for key in PROXY_KEYS:
                    env.pop(key, None)
                env.update(
                    AUTORESEARCH_PROXY_REQUIRED="1",
                    AUTORESEARCH_CONNECTION_ID="",
                    AUTORESEARCH_CONNECTION_GATEWAY=self.connections.base_url,
                    AUTORESEARCH_CONNECTION_TOKEN=self.connections.token,
                )
            env["PYTHONPATH"] = str(WEB_ROOT.parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
            env["AUTORESEARCH_WORKER_TOKEN"] = self.worker_token
            command = [
                sys.executable,
                "-m",
                "workbench.server",
                "--port",
                str(self.port),
                "--workspace",
                str(self.workspace),
                "--data-dir",
                str(self.data_dir),
            ]
            if self.isolated:
                command.extend(["--tenant-root", str(self.workspace)])
            with self.log_path.open("ab") as log:
                self.process = subprocess.Popen(
                    command,
                    cwd=self.workspace,
                    env=env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            self.message = "研究服务正在启动。"

    def request(self, path: str, method: str = "GET", timeout: float = 3) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(
                method,
                path,
                body=b"{}" if method == "POST" else None,
                headers={
                    "Content-Type": "application/json",
                    "X-AutoResearch-Worker": self.worker_token,
                },
            )
            response = conn.getresponse()
            data = json.loads(response.read())
            if response.status >= 400:
                raise ValueError(data.get("error", "服务请求失败。"))
            return data
        finally:
            conn.close()

    def state(self) -> dict:
        alive = self.process is not None and self.process.poll() is None
        ready = False
        if alive:
            try:
                ready = self.request("/api/runtime", timeout=1).get("status") == "ok"
            except (OSError, ValueError, http.client.HTTPException):
                pass
        return {
            "supervised": True,
            "connected": ready,
            "restarting": self.restarting,
            "message": "服务已连接，可在网页管理任务。"
            if ready and self.message == "研究服务正在启动。"
            else self.message,
            "settings": self.settings,
            "log_url": "/api/service/log",
        }

    def restart(self, settings: dict | None = None) -> None:
        with self.lock:
            if self.restarting:
                raise ValueError("服务正在重启，请等待状态更新。")
            if settings is not None:
                cleaned = {}
                for key in ("CODEX_CLI", "LATEX_COMPILER"):
                    value = str(settings.get(key, "")).strip()
                    if value:
                        resolved = shutil.which(value)
                        if not resolved:
                            raise ValueError(f"找不到可执行文件：{value}")
                        cleaned[key] = resolved
                self.settings = cleaned
                temporary = self.settings_path.with_name(
                    ".service-settings-" + secrets.token_hex(8)
                )
                try:
                    temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2))
                    temporary.replace(self.settings_path)
                finally:
                    temporary.unlink(missing_ok=True)
            self.restarting = True
            self.message = "正在停止任务控制器并保存恢复点；保留训练进程。"
            threading.Thread(target=self._restart, daemon=True).start()

    def _restart(self) -> None:
        try:
            if self.process and self.process.poll() is None:
                self.request("/api/runtime/prepare-restart", "POST", timeout=10)
                deadline = time.monotonic() + 45
                while not self.request("/api/runtime")["idle"]:
                    if time.monotonic() >= deadline:
                        self.request("/api/runtime/activate", "POST")
                        raise ValueError("当前控制器尚未退出，保留服务。可查看日志后再次重启。")
                    time.sleep(0.5)
                self.process.terminate()
                self.process.wait(timeout=10)
            self.start()
            self.message = "服务已重新启动；原任务保持暂停，可在网页继续。"
        except (OSError, ValueError, http.client.HTTPException, subprocess.TimeoutExpired) as error:
            self.message = f"重启未完成：{error}。查看服务日志定位原因。"
        finally:
            self.restarting = False

    def close(self) -> None:
        with self.lock:
            self.closed = True
            process = self.process
        if process and process.poll() is None:
            try:
                self.request("/api/runtime/prepare-restart", "POST", timeout=10)
            except (OSError, ValueError, http.client.HTTPException):
                pass
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, service: Service | None = None, platform=None, **kwargs):
        self.service = service
        self.platform = platform
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def respond(self, value: dict, status: int = 200, *, cookie: str | None = None) -> None:
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def route(self) -> None:
        if self.platform is not None:
            self.platform.connections.base_url = f"http://127.0.0.1:{self.server.server_port}"
            try:
                self.account_route()
            except AccountError as error:
                self.respond({"error": str(error)}, error.status)
            except (ValueError, OSError, TypeError, AttributeError) as error:
                self.respond({"error": str(error)}, 400)
            return
        self.service_route()

    def read_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise AccountError("请求需要使用 JSON。", 415)
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 16384:
            raise AccountError("账号请求为空或超过 16 KB。")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise AccountError("请求必须为 JSON 对象。")
        return payload

    def session_cookie(self, token: str, *, clear: bool = False) -> str:
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = token
        item = cookie[COOKIE_NAME]
        item["path"] = "/"
        item["httponly"] = True
        item["samesite"] = "Lax"
        item["max-age"] = 0 if clear else SESSION_SECONDS
        if self.platform.secure_cookies:
            item["secure"] = True
        return item.OutputString()

    def account_route(self) -> None:
        path = urlsplit(self.path).path.rstrip("/")
        connections = self.platform.connections
        if path.startswith("/api/internal/connection/"):
            if self.command != "GET" or not hmac.compare_digest(
                self.headers.get("X-AutoResearch-Network", ""), connections.token
            ):
                raise AccountError("内部连接接口拒绝访问。", 403)
            self.respond({"proxy_url": connections.proxy_url(path.rsplit("/", 1)[1])})
            return
        accounts = self.platform.accounts
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            jar = SimpleCookie()
        token = jar[COOKIE_NAME].value if COOKIE_NAME in jar else ""
        session = accounts.session(token)
        if self.command not in {"GET", "HEAD"}:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                raise AccountError("此操作需要从平台页面发起。", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise AccountError("此操作需要从平台页面发起。", 403)

        if path == "/api/auth/session" and self.command == "GET":
            self.respond(
                {
                    "authenticated": bool(session),
                    "setup_required": accounts.needs_setup(),
                    "registration_open": accounts.registration_open(),
                    "connection": connections.state(connections.resolve(self.client_address, self.server.server_port)),
                    **(session or {}),
                }
            )
            return
        if (
            path in {"/api/auth/setup", "/api/auth/register", "/api/auth/login"}
            and self.command == "POST"
        ):
            payload = self.read_json()
            if path != "/api/auth/login":
                accounts.create(payload, setup=path == "/api/auth/setup")
            user, new_token = accounts.login(payload, self.client_address[0])
            self.respond(
                {"user": user},
                200 if path == "/api/auth/login" else 201,
                cookie=self.session_cookie(new_token),
            )
            return

        public_files = {"/login.html", "/login.js", "/accounts.css", "/styles.css", "/shell.css"}
        if path in public_files and self.command in {"GET", "HEAD"}:
            (super().do_GET if self.command == "GET" else super().do_HEAD)()
            return
        if path == "/auto-design/assets/the-thainker-logo.png" and self.command in {"GET", "HEAD"}:
            self.send_file(
                WEB_ROOT.parents[1] / "auto_design/web/assets/the-thainker-logo.png", "image/png"
            )
            return
        if not session:
            if "/api/" in path:
                raise AccountError("请先登录账号。", 401)
            self.send_response(303)
            self.send_header("Location", "/login.html?next=" + quote(self.path, safe=""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        user = session["user"]
        decoded_path = urlsplit(self.path).path
        for _ in range(3):
            decoded_path = unquote(decoded_path)
        if "\\" in decoded_path or ".." in decoded_path.split("/"):
            raise AccountError("请求路径无效。", 400)
        if path.startswith("/auto-") and "/api/" not in path:
            _module, _, resource = path.lstrip("/").partition("/")
            public_resource = resource in {
                "",
                "index.html",
                "app.js",
                "styles.css",
            } or resource.startswith(("assets/", "default-references/"))
            if not public_resource:
                raise AccountError("资源不存在。", 404)
        expected_account = self.headers.get("X-AutoResearch-Account")
        if expected_account and expected_account != user["id"]:
            raise AccountError("当前浏览器已切换账号，请刷新页面。", 401)
        if self.command not in {"GET", "HEAD"}:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(supplied, session["csrf_token"]):
                raise AccountError("页面会话已更新，请刷新后重试。", 403)
        if path == "/api/auth/logout" and self.command == "POST":
            accounts.logout(token)
            self.respond({"status": "logged_out"}, cookie=self.session_cookie("", clear=True))
            return
        if path == "/api/auth/password" and self.command == "POST":
            payload = self.read_json()
            accounts.change_password(
                user["id"], payload.get("current_password"), payload.get("password")
            )
            self.respond({"status": "password_changed"}, cookie=self.session_cookie("", clear=True))
            return
        if path == "/api/connection" and self.command == "GET":
            self.respond(connections.state(connections.resolve(self.client_address, self.server.server_port)))
            return
        if path == "/api/connection/test" and self.command == "POST":
            connection_id = connections.resolve(self.client_address, self.server.server_port)
            self.respond(connections.test(connection_id, self.platform.workspace), 202)
            return
        if path.startswith("/api/admin/"):
            if user["role"] != "admin":
                raise AccountError("此操作需要管理员账号。", 403)
            if path == "/api/admin/users" and self.command == "GET":
                self.respond(
                    {
                        "users": accounts.list_users(),
                        "registration_open": accounts.registration_open(),
                    }
                )
            elif path == "/api/admin/settings" and self.command == "POST":
                accounts.set_registration(self.read_json().get("registration_open"))
                self.respond({"registration_open": accounts.registration_open()})
            elif path.startswith("/api/admin/users/") and self.command == "POST":
                updated = accounts.update_user(path.split("/")[-1], self.read_json())
                if not updated["active"]:
                    self.platform.stop_user(updated["id"])
                self.respond({"user": updated})
            else:
                raise AccountError("接口不存在。", 404)
            return
        if path == "/accounts.html" and user["role"] != "admin":
            raise AccountError("此页面需要管理员账号。", 403)
        if self.command in {"GET", "HEAD"} and not path.startswith(("/api/", "/auto-")):
            if path in {"", "/index.html", "/journey.html", "/accounts.html"}:
                page = WEB_ROOT / (path.lstrip("/") or "index.html")
                self.send_file(page, "text/html; charset=utf-8", account_page=True)
            else:
                (super().do_GET if self.command == "GET" else super().do_HEAD)()
            return
        if path == "/api/service/restart" and self.command == "POST":
            payload = self.read_json()
            if payload.get("settings") is not None and user["role"] != "admin":
                raise AccountError("统一 Codex 和编译器配置由管理员维护。", 403)
            self.service = self.platform.service(user)
            self.service.restart(payload.get("settings"))
            self.respond({"status": "restarting"}, 202)
            return
        if path in {"/api/runtime/prepare-restart", "/api/runtime/activate"}:
            raise AccountError("请使用当前账号的服务管理入口。", 403)
        self.service = self.platform.service(user)
        self.service_route()

    @staticmethod
    def account_html(content: bytes) -> bytes:
        return content.replace(
            b"<head>",
            b'<head><link rel="stylesheet" href="/accounts.css"><script src="/account.js"></script>',
            1,
        )

    def send_file(self, path: Path, content_type: str, *, account_page: bool = False) -> None:
        content = path.read_bytes()
        if account_page:
            content = self.account_html(content)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def service_route(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/service" and self.command == "GET":
            self.respond(self.service.state())
            return
        if path == "/api/service/log" and self.command == "GET":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            with self.service.log_path.open("rb") as log:
                shutil.copyfileobj(log, self.wfile)
            return
        if path == "/api/service/restart" and self.command == "POST":
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("无效的服务操作请求。")
                payload = json.loads(self.rfile.read(size))
                self.service.restart(payload.get("settings"))
                self.respond({"status": "restarting"}, 202)
            except (ValueError, OSError, TypeError, AttributeError) as error:
                self.respond({"error": str(error)}, 400)
            return
        # Static workbench files remain available even when its worker has exited.
        if self.command in {"GET", "HEAD"} and not path.startswith(("/api/", "/auto-")):
            (super().do_GET if self.command == "GET" else super().do_HEAD)()
            return
        if self.service.restarting and self.command not in {"GET", "HEAD"}:
            self.respond({"error": "服务正在重启，请等待重新连接后操作。"}, 503)
            return
        conn = http.client.HTTPConnection("127.0.0.1", self.service.port, timeout=60)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 32 * 1024 * 1024:
                raise ValueError("请求超过 32 MB。")
            body = self.rfile.read(size) if size else None
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in {"host", "connection", "cookie", "x-autoresearch-worker", HEADER.lower(), "x-autoresearch-network"}
            }
            headers["X-AutoResearch-Worker"] = self.service.worker_token
            if self.platform is not None:
                headers[HEADER] = self.platform.connections.resolve(self.client_address, self.server.server_port) or ""
            headers["Host"] = self.headers.get("Host", "")
            module = path.split("/")[1]
            is_module_page = module.startswith("auto-") and path in {
                f"/{module}",
                f"/{module}/index.html",
            }
            method = (
                "GET"
                if self.platform is not None and self.command == "HEAD" and is_module_page
                else self.command
            )
            conn.request(method, self.path, body=body, headers=headers)
            response = conn.getresponse()
        except (OSError, ValueError, http.client.HTTPException) as error:
            self.respond({"error": f"研究服务不可用，请返回工作台启动服务。{error}"}, 503)
            conn.close()
            return
        try:
            page = None
            if self.platform is not None and is_module_page and response.status == 200:
                page = self.account_html(response.read())
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() == "content-length" and page is not None:
                    continue
                if key.lower() not in {
                    "connection",
                    "transfer-encoding",
                    "server",
                    "date",
                    "cache-control",
                }:
                    self.send_header(key, value)
            if page is not None:
                self.send_header("Content-Length", str(len(page)))
            elif self.platform is not None and response.getheader("Content-Type", "").startswith(
                "text/html"
            ):
                self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-downloads")
            self.end_headers()
            if self.command != "HEAD":
                if page is not None:
                    self.wfile.write(page)
                else:
                    while chunk := response.read(64 * 1024):
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    do_GET = route
    do_HEAD = route
    do_POST = route
    do_PUT = route
    do_DELETE = route

    def log_message(self, format, *args):
        pass


class AccountPlatform:
    """One worker per account keeps module-level state in separate processes."""

    def __init__(self, workspace: Path, data_dir: Path, *, secure_cookies: bool = False):
        self.workspace = workspace.resolve()
        self.data_dir = data_dir.resolve()
        self.accounts = Accounts(self.data_dir)
        self.secure_cookies = secure_cookies
        self.services: dict[str, Service] = {}
        self.lock = threading.RLock()
        self.closed = False
        self.connections = Connections()

    def service(self, user: dict) -> Service:
        with self.lock:
            if self.closed:
                raise AccountError("平台正在停止，请稍后重试。", 503)
            previous = self.services.get(user["id"])
            if previous is not None and previous.closed:
                if previous.process is not None and previous.process.poll() is None:
                    raise AccountError("当前账号的服务正在停止，请稍后重试。", 503)
                del self.services[user["id"]]
            if user["id"] not in self.services:
                if user["legacy_owner"]:
                    workspace, directory = self.workspace, self.data_dir
                else:
                    root = self.data_dir / "users" / user["id"]
                    root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    workspace = root / "workspace"
                    directory = workspace / "assets/output/workbench"
                    workspace.mkdir(exist_ok=True)
                    instructions = self.workspace / "AGENTS.md"
                    target = workspace / "AGENTS.md"
                    if instructions.is_file() and not target.exists():
                        target.write_text(
                            instructions.read_text()
                            + "\n\n# 当前账号工作目录\n\n当前账号的新任务和产物以本目录为 workspace，遵守上面的共享 GPU 资源边界。\n"
                        )
                service = Service(workspace, directory, isolated=not bool(user["legacy_owner"]), connections=self.connections)
                # All accounts inherit one server-managed Codex/compiler configuration.
                service.settings_path = self.data_dir / "service_settings.json"
                service.settings = (
                    json.loads(service.settings_path.read_text())
                    if service.settings_path.is_file()
                    else {}
                )
                self.services[user["id"]] = service
                service.start()
            return self.services[user["id"]]

    def stop_user(self, user_id: str) -> None:
        with self.lock:
            service = self.services.get(user_id)
            if service:
                with service.lock:
                    service.closed = True
        if service:
            threading.Thread(target=service.close, daemon=True).start()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            services = list(self.services.values())
        for service in services:
            service.close()
        self.connections.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoResearch 工作台与浏览器服务恢复入口")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--secure-cookies",
        action="store_true",
        default=os.environ.get("AUTORESEARCH_SECURE_COOKIES") == "1",
    )
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error("workspace 必须是已存在的目录")
    platform = AccountPlatform(
        workspace,
        args.data_dir or workspace / "assets/output/workbench",
        secure_cookies=args.secure_cookies,
    )
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, platform=platform))

    def stop_server(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    try:
        print(f"AutoResearch: http://{args.host}:{server.server_port}/", flush=True)
        if platform.accounts.needs_setup():
            print(
                "管理员初始化口令（仅用于首次创建管理员） "
                + platform.accounts.setup_path.read_text(),
                flush=True,
            )
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        platform.close()
        server.server_close()


if __name__ == "__main__":
    main()
