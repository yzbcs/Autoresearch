"""Standard-library HTTP server for the native AutoDesign web workspace."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workbench.connection_context import ConnectionHandlerMixin
from auto_design.codex_runner import resolve_codex_cli
from auto_design.orchestration import TaskManager

WEB_ROOT = Path(__file__).resolve().parent


class AppHandler(ConnectionHandlerMixin, SimpleHTTPRequestHandler):
    def __init__(self, *args, manager: TaskManager, workspace: Path, **kwargs):
        self.manager = manager
        self.workspace = workspace
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_payload(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 8 * 1024 * 1024:
            raise ValueError("请求为空或超过 8 MB。")
        data = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(data, dict):
            raise TypeError("请求必须是 JSON 对象。")
        return data

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        try:
            if path == "/api/health":
                try:
                    cli, error = resolve_codex_cli(), None
                except RuntimeError as exc:
                    cli, error = None, str(exc)
                self.send_json(
                    {
                        "status": "ok",
                        "codex_cli": cli,
                        "error": error,
                        "workspace": str(self.workspace),
                    }
                )
                return
            if path == "/api/tasks":
                self.send_json({"tasks": self.manager.list()})
                return
            parts = path.split("/")
            if len(parts) == 4 and parts[1:3] == ["api", "tasks"]:
                self.send_json(self.manager.detail(parts[3]))
                return
            if len(parts) >= 6 and parts[1:3] == ["api", "tasks"] and parts[4] == "files":
                self.send_artifact(parts[3], "/".join(parts[5:]))
                return
            if path.startswith("/api/"):
                self.send_json({"error": "接口不存在。"}, 404)
                return
            super().do_GET()
        except (ValueError, OSError) as error:
            self.send_json({"error": str(error)}, 400)

    def send_artifact(self, task_id: str, relative: str) -> None:
        run_dir = Path(self.manager.get(task_id)["run_dir"]).resolve()
        target = (run_dir / relative).resolve()
        if not target.is_relative_to(run_dir) or not target.is_file():
            raise ValueError("产物不存在或不属于当前任务目录。")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with target.open("rb") as source:
            while chunk := source.read(64 * 1024):
                self.wfile.write(chunk)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        try:
            payload = self.read_payload()
            if path == "/api/tasks":
                task = self.manager.create(
                    str(payload.get("title", "")),
                    str(payload.get("idea", "")),
                    str(payload.get("workspace", self.workspace)),
                    str(payload.get("scope", "full")),
                )
                self.send_json(task, 201)
                return
            if path == "/api/tasks/import":
                task = self.manager.import_run(
                    str(payload.get("title", "")),
                    str(payload.get("run_dir", "")),
                    str(payload.get("workspace", self.workspace)),
                )
                self.send_json(task, 201)
                return
            parts = path.split("/")
            if len(parts) == 5 and parts[1:3] == ["api", "tasks"]:
                task_id, action = parts[3:5]
                if action in {"start", "resume"}:
                    task = self.manager.start(task_id, payload.get("scope"), str(payload.get("recovery_note", "")))
                elif action == "pause":
                    task = self.manager.pause(task_id)
                elif action == "interrupt":
                    task = self.manager.interrupt(task_id)
                elif action == "decision":
                    task = self.manager.decide(
                        task_id,
                        str(payload.get("revision_id", "")),
                        str(payload.get("decision", "")),
                    )
                else:
                    self.send_json({"error": "接口不存在。"}, 404)
                    return
                self.send_json(task, 202)
                return
            self.send_json({"error": "接口不存在。"}, 404)
        except (ValueError, OSError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)


def create_server(
    host: str, port: int, manager: TaskManager, workspace: Path
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), partial(AppHandler, manager=manager, workspace=workspace)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AutoDesign 原生网页工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error("workspace 必须是已存在的目录")
    data_dir = args.data_dir or workspace / "assets" / "output" / "auto_design"
    manager = TaskManager(data_dir)
    server = create_server(args.host, args.port, manager, workspace)
    print(f"AutoDesign: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
