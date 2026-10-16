"""Standalone server and handler mounted at /auto-table/ by the workbench."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from auto_table.application import Application
from auto_table.engine.table_types import available_table_types
from auto_table.engine.templates import available_templates
from auto_writing.web import serve as writing

WEB_ROOT = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 32 * 1024 * 1024


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, app, **kwargs):
        self.app = app
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/")
        if not path.startswith("/api/"):
            return super().do_HEAD() if self.command == "HEAD" else super().do_GET()
        parts = [unquote(part) for part in path.split("/")]
        try:
            if path == "/api/health":
                return self.send_json(
                    {
                        "status": "ok",
                        "codex_cli": bool(shutil.which("codex") or os.environ.get("CODEX_CLI")),
                        "latex": bool(writing.latex_compiler()),
                    }
                )
            if path == "/api/catalog":
                return self.send_json(
                    {"templates": available_templates(), "types": available_table_types()}
                )
            if path == "/api/projects":
                return self.send_json(
                    {
                        "projects": [
                            {
                                k: p[k]
                                for k in (
                                    "id",
                                    "title",
                                    "mode",
                                    "status",
                                    "step",
                                    "created_at",
                                    "updated_at",
                                )
                            }
                            for p in self.app.list()
                        ]
                    }
                )
            if path == "/api/writing-projects":
                projects = []
                for file in writing.WRITING_RUNS_ROOT.glob("*/project.json"):
                    p = json.loads(file.read_text(encoding="utf-8"))
                    publication = writing.publication_dir(file.parent)
                    if (publication / "manuscript-latex.zip").is_file():
                        projects.append({"id": p["id"], "title": p["title"]})
                return self.send_json({"projects": projects})
            if len(parts) == 4 and parts[1:3] == ["api", "projects"]:
                p = self.app.load(parts[3])
                p["artifacts"] = self.app.artifacts(parts[3])
                return self.send_json(p)
            if len(parts) >= 7 and parts[1:3] == ["api", "projects"] and parts[4] == "files":
                file = self.app.artifact(parts[3], parts[5], "/".join(parts[6:]))
                self.send_response(200)
                self.send_header(
                    "Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                )
                self.send_header("Content-Length", str(file.stat().st_size))
                self.end_headers()
                if self.command != "HEAD":
                    with file.open("rb") as handle:
                        shutil.copyfileobj(handle, self.wfile)
                return
            self.send_json({"error": "接口不存在。"}, 404)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)

    do_HEAD = do_GET

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_REQUEST_BYTES:
                raise ValueError("请求为空或超过 32 MB。")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise TypeError("请求必须为 JSON 对象。")
            path = urlsplit(self.path).path.rstrip("/")
            parts = [unquote(part) for part in path.split("/")]
            if path == "/api/projects":
                return self.send_json(self.app.create(payload), 201)
            if path == "/api/import-writing":
                project = self.app.import_writing(payload)
                return self.send_json(project, 201)
            if len(parts) == 5 and parts[1:3] == ["api", "projects"]:
                if parts[4] == "start":
                    return self.send_json(self.app.start(parts[3], payload), 202)
                if parts[4] == "stop":
                    return self.send_json(self.app.stop(parts[3]))
            self.send_json({"error": "接口不存在。"}, 404)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)

    def log_message(self, format, *args):
        if "/api/" not in self.path:
            super().log_message(format, *args)


def create_server(host, port, app):
    return ThreadingHTTPServer((host, port), partial(AppHandler, app=app))


def main(argv=None):
    parser = argparse.ArgumentParser(description="The ThAInker · Auto Table")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    app = Application(args.workspace, args.data_dir)
    server = create_server(args.host, args.port, app)
    print(f"Auto Table: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


if __name__ == "__main__":
    main()
