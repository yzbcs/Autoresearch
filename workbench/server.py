"""One public HTTP address, with each module retaining its own handler and state."""

from __future__ import annotations

import argparse
import http.client
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from auto_design.orchestration import TaskManager
from auto_design.web.serve import create_server as create_design_server
from auto_figure.application import Application as FigureApplication
from auto_figure.web.serve import create_server as create_figure_server
from auto_search.web import serve as search
from auto_table.application import Application as TableApplication
from auto_table.web.serve import create_server as create_table_server
from auto_writing.web import serve as writing

from .deletion import delete as delete_task
from .pipeline import PipelineManager
from .journey import snapshot as journey_snapshot

WEB_ROOT = Path(__file__).resolve().parent / "web"
MODULES = ("auto-search", "auto-design", "auto-writing", "auto-table", "auto-figure")
MAX_REQUEST_BYTES = writing.MAX_REQUEST_BYTES
HOP_HEADERS = {"connection", "transfer-encoding", "keep-alive", "upgrade"}


def add_navigation(content: bytes, module: str) -> bytes:
    html = content.decode("utf-8")
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/module-nav.css">'
        '<link rel="stylesheet" href="/layout.css">'
        '<script src="/module-nav.js" defer></script>'
        '<link rel="stylesheet" href="/list-actions.css">'
        '<script src="/list-actions.js" defer></script></head>',
        1,
    )
    html = html.replace("<body>", f'<body class="workbench-module" data-module="{module}">', 1)
    return html.encode("utf-8")


class WorkbenchHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, modules: dict[str, ThreadingHTTPServer], workbench=None, **kwargs):
        self.modules = modules
        self.workbench = workbench
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def route(self) -> None:
        url = urlsplit(self.path)
        if url.path.startswith("/api/") and self.workbench is not None:
            self.workbench_api(url.path.rstrip("/"))
            return
        module = url.path.split("/")[1]
        if module not in self.modules:
            if self.command == "GET":
                super().do_GET()
            elif self.command == "HEAD":
                super().do_HEAD()
            else:
                self.send_error(404, "Unknown module")
            return
        if url.path == f"/{module}":
            self.send_response(307)
            self.send_header("Location", urlunsplit(("", "", f"/{module}/", url.query, "")))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        local_path = url.path[len(module) + 1 :]
        if self.command == "DELETE":
            from urllib.parse import unquote
            pieces = unquote(local_path).strip("/").split("/")
            if len(pieces) == 3 and pieces[:2] in (["api", "runs"], ["api", "writings"], ["api", "tasks"], ["api", "projects"]):
                self.workbench_api(f"/api/items/{module.removeprefix('auto-')}/{pieces[2]}")
                return
        target = urlunsplit(("", "", local_path, url.query, ""))
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if not 0 <= size <= MAX_REQUEST_BYTES:
            self.send_error(413, "Request exceeds 32 MB")
            return
        body = self.rfile.read(size) if size else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_HEADERS | {"host", "accept-encoding"}
        }
        is_page = local_path in {"/", "/index.html"}
        method = "GET" if self.command == "HEAD" and is_page else self.command
        backend = self.modules[module]
        connection = http.client.HTTPConnection("127.0.0.1", backend.server_port, timeout=60)
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as error:
            connection.close()
            data = json.dumps({"error": f"{module} 服务暂时不可用：{error}"}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            return
        try:
            page = None
            if is_page and response.status == 200:
                page = add_navigation(response.read(), module)
            self.send_response(response.status)
            for key, value in response.getheaders():
                name = key.lower()
                if name in HOP_HEADERS | {"server", "date", "cache-control"}:
                    continue
                if name == "content-length" and page is not None:
                    continue
                if name == "location" and value.startswith("/"):
                    value = f"/{module}{value}"
                self.send_header(key, value)
            if page is not None:
                self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            if self.command == "HEAD":
                return
            if page is not None:
                self.wfile.write(page)
            else:
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # Navigating to another module can close the old page's pending request.
            pass
        finally:
            connection.close()

    do_GET = route
    do_HEAD = route
    do_POST = route
    do_PUT = route
    do_DELETE = route

    def workbench_api(self, path: str) -> None:
        app = self.workbench
        status = 200
        try:
            payload = {}
            if self.command == "POST":
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_REQUEST_BYTES:
                    raise ValueError("请求为空或超过 32 MB。")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是 JSON 对象。")
            parts = path.split("/")
            if len(parts) == 5 and parts[1:3] == ["api", "items"] and self.command == "DELETE":
                from urllib.parse import unquote
                result = delete_task(app, parts[3], unquote(parts[4]))
            elif path == "/api/pipelines" and self.command == "GET":
                result = {"pipelines": app.pipeline.list()}
            elif path == "/api/pipelines" and self.command == "POST":
                result, status = app.pipeline.create(payload), 201
            elif len(parts) == 4 and parts[1:3] == ["api", "pipelines"] and self.command == "GET":
                with app.pipeline.lock:
                    flow = app.pipeline.get(parts[3])
                    result = {**flow, "candidates": app.pipeline.candidates(flow)}
            elif len(parts) == 5 and parts[1:3] == ["api", "pipelines"] and parts[4] == "journey" and self.command == "GET":
                result = journey_snapshot(app, parts[3])
            elif len(parts) == 5 and parts[1:3] == ["api", "pipelines"] and self.command == "POST":
                result = app.pipeline.action(parts[3], parts[4], payload)
            elif path == "/api/runtime" and self.command == "GET":
                result = app.runtime_state()
            elif path == "/api/runtime/prepare-restart" and self.command == "POST":
                app.prepare_restart()
                result = app.runtime_state()
            elif path == "/api/runtime/activate" and self.command == "POST":
                app.pipeline.start()
                result = app.runtime_state()
            else:
                result, status = {"error": "接口不存在。"}, 404
        except (ValueError, OSError, TypeError, KeyError) as error:
            result, status = {"error": str(error)}, 400
        data = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        if "/api/" not in self.path:
            super().log_message(format, *args)


class Workbench:
    def __init__(self, workspace: Path, data_dir: Path, host: str = "127.0.0.1", port: int = 8760):
        self.workspace = workspace.resolve()
        self.data_dir = data_dir.resolve()
        self.modules: dict[str, ThreadingHTTPServer] = {}
        self.threads: list[threading.Thread] = []
        search.RUNS_ROOT = self.data_dir / "auto_search"
        writing.WRITING_RUNS_ROOT = self.data_dir / "auto_writing"
        search.RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        writing.WRITING_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        writing.migrate_existing_research_references()
        self.design = TaskManager(self.data_dir / "auto_design")
        self.table = TableApplication(self.workspace, self.data_dir / "auto_table")
        self.figure = FigureApplication(self.workspace, self.data_dir / "auto_figure", table=self.table)
        self.pipeline = PipelineManager(
            self.data_dir / "pipelines", self.workspace, self.design, self.table, self.figure
        )
        try:
            self.modules["auto-search"] = ThreadingHTTPServer(
                ("127.0.0.1", 0), partial(search.AppHandler, directory=str(search.WEB_ROOT))
            )
            self.modules["auto-design"] = create_design_server(
                "127.0.0.1", 0, self.design, self.workspace
            )
            self.modules["auto-writing"] = ThreadingHTTPServer(
                ("127.0.0.1", 0), partial(writing.AppHandler, directory=str(writing.WEB_ROOT))
            )
            self.modules["auto-table"] = create_table_server("127.0.0.1", 0, self.table)
            self.modules["auto-figure"] = create_figure_server("127.0.0.1", 0, self.figure)
            self.server = ThreadingHTTPServer(
                (host, port), partial(WorkbenchHandler, modules=self.modules, workbench=self)
            )
        except OSError:
            for server in self.modules.values():
                server.server_close()
            raise

    def start_modules(self) -> None:
        for name, server in self.modules.items():
            thread = threading.Thread(target=server.serve_forever, daemon=True, name=name)
            thread.start()
            self.threads.append(thread)
        self.pipeline.start()

    def close(self) -> None:
        self.pipeline.close()
        self.figure.close()
        self.table.close()
        self.server.server_close()
        for server in self.modules.values():
            if self.threads:
                server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()

    def runtime_state(self) -> dict:
        searches = [
            j
            for j in search.JOB_MANAGER.snapshots()
            if not search.JOB_MANAGER.get(j["id"]).finished_event.is_set()
        ]
        with writing.GENERATION_MANAGER.lock:
            writing_jobs = [j.id for j in writing.GENERATION_MANAGER.jobs.values()]
        with self.design.lock:
            design_jobs = [
                t["id"]
                for t in self.design.list()
                if t["status"] in {"running", "queued", "pausing"}
            ]
        with self.table.lock:
            table_jobs = list(self.table.jobs)
        with self.figure.lock:
            figure_jobs = list(self.figure.jobs)
        return {
            "status": "ok",
            "active_searches": [j["id"] for j in searches],
            "active_designs": design_jobs,
            "active_writing": writing_jobs,
            "active_tables": table_jobs,
            "active_figures": figure_jobs,
            "idle": not (searches or design_jobs or writing_jobs or table_jobs or figure_jobs),
        }

    def prepare_restart(self) -> None:
        self.pipeline.close()
        self.figure.close()
        self.table.close()
        with self.pipeline.lock:
            for flow in self.pipeline.flows.values():
                if flow["status"] in {"running", "waiting_review"}:
                    self.pipeline.update(flow, "paused", "正在重启服务；恢复连接后可继续原流程。")
        for task in self.design.list():
            if task["status"] in {"queued", "running", "pausing"}:
                self.design.interrupt(task["id"])
        for job in search.JOB_MANAGER.snapshots():
            if job["status"] not in {"ready", "failed", "cancelled"}:
                search.JOB_MANAGER.stop(job["id"])
        manager = writing.GENERATION_MANAGER
        with manager.lock:
            for project_id in list(manager.automation_threads):
                manager.pause_auto(project_id)
            for job in list(manager.jobs.values()):
                manager.cancel(job.id)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The ThAInker · AutoResearch 四模块工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error("workspace 必须是已存在的目录")
    data_dir = (args.data_dir or workspace / "assets/output/workbench").expanduser().resolve()
    app = Workbench(workspace, data_dir, args.host, args.port)
    app.start_modules()
    print(f"AutoResearch: http://{args.host}:{app.server.server_port}/", flush=True)
    print(f"Workspace: {workspace}\nTask data: {data_dir}", flush=True)
    try:
        app.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


if __name__ == "__main__":
    main()
