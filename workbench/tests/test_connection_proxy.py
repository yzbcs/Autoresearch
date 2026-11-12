import json
import queue
import socket
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from workbench import connection_proxy
from workbench.accounts import Accounts
from workbench.connection_context import (
    HEADER,
    ConnectionHandlerMixin,
    background_thread,
    codex_environment,
    connection_environment,
    connection_scope,
    current_connection,
)
from workbench.connection_proxy import Connections
from workbench.tests.test_accounts import PASSWORD, Browser
from workbench.tests.test_workbench import app as workbench_app

app = workbench_app


def test_gateway_sigterm_closes_its_research_worker(tmp_path):
    data_dir = tmp_path / "data"
    accounts = Accounts(data_dir)
    accounts.create(
        {"username": "admin", "password": PASSWORD, "setup_token": accounts.setup_path.read_text()},
        setup=True,
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "workbench",
            "--port",
            "0",
            "--workspace",
            str(tmp_path),
            "--data-dir",
            str(data_dir),
        ],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        first_line = lines.get(timeout=15)
        assert first_line.startswith("AutoResearch: http://127.0.0.1:"), first_line
        port = int(first_line.strip().rstrip("/").rsplit(":", 1)[1])
        browser = Browser(port)
        browser.login("admin")
        assert browser.request("/api/service")[0] == 200
        process.terminate()
        assert process.wait(timeout=20) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)


def test_cli_wrapper_allows_discovery_and_scopes_proxy_for_model_calls(tmp_path):
    native = tmp_path / ".tools/codex/libexec/codex"
    native.parent.mkdir(parents=True)
    native.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "${HTTP_PROXY:-}" "$@"\n')
    native.chmod(0o755)
    wrapper = tmp_path / "ycodex"
    source = Path(__file__).resolve().parents[2] / "deployment/ycodex"
    wrapper.write_text(
        source.read_text().replace("/root/autodl-tmp/yzb/autoresearch", str(tmp_path))
    )
    env = {"PATH": "/usr/bin:/bin", "AUTORESEARCH_PROXY_REQUIRED": "1"}
    version = subprocess.run(
        ["bash", str(wrapper), "--version"], env=env, capture_output=True, text=True, check=False
    )
    assert version.returncode == 0
    missing = subprocess.run(
        ["bash", str(wrapper), "exec", "probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 78
    env.update(AUTORESEARCH_PROXY_URL="http://127.0.0.1:23456", HTTP_PROXY="http://wrong:7890")
    result = subprocess.run(
        ["bash", str(wrapper), "--no-daemon", "exec", "probe"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "http://127.0.0.1:23456"
    assert result.stdout.count("--no-daemon") == 1
    assert "supports_websockets=false" in result.stdout


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        content = self.request.recv(100)
        self.request.sendall(self.server.label + content)


@pytest.fixture
def routes(monkeypatch):
    alive = {"alice-device": True, "bob-device": True}
    upstreams = []
    for label in [b"alice:", b"bob:"]:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
        server.label = label
        threading.Thread(target=server.serve_forever, daemon=True).start()
        upstreams.append(server)
    forwards = {
        name: {
            "pid": index + 100,
            "started": name,
            "inode": str(index),
            "port": server.server_address[1],
        }
        for index, (name, server) in enumerate(zip(alive, upstreams))
    }
    monkeypatch.setattr(connection_proxy, "ssh_forward", lambda peer, port: forwards[peer[0]])
    monkeypatch.setattr(
        connection_proxy, "forward_alive", lambda forward: alive[forward["started"]]
    )
    manager = Connections(enabled=True)
    alice = manager.resolve(("alice-device", 1), 8760)
    bob = manager.resolve(("bob-device", 2), 8760)
    try:
        yield manager, alice, bob, alive
    finally:
        manager.close()
        for server in upstreams:
            server.shutdown()
            server.server_close()


def relay_read(url):
    port = int(url.rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
        client.sendall(b"proof")
        client.shutdown(socket.SHUT_WR)
        return client.recv(100)


def test_independent_connection_relays_and_disconnect_never_reuses_other_proxy(routes):
    manager, alice, bob, alive = routes
    assert alice != bob
    assert manager.resolve(("alice-device", 99), 8760) == alice
    first = manager.proxy_url(alice)
    second = manager.proxy_url(bob)
    assert first != second
    assert relay_read(first) == b"alice:proof"
    assert relay_read(second) == b"bob:proof"
    alive["alice-device"] = False
    with pytest.raises(ValueError, match="断开"):
        manager.proxy_url(alice)
    assert b"502 SSH tunnel disconnected" in relay_read(first)
    assert relay_read(second) == b"bob:proof"


def test_context_is_captured_by_each_background_job_and_restored():
    started = threading.Event()
    results = []

    def capture():
        started.wait(3)
        results.append(current_connection())

    with connection_scope("device-a"):
        first = background_thread(target=capture)
        first.start()
    with connection_scope("device-b"):
        second = background_thread(target=capture)
        second.start()
    assert current_connection() is None
    started.set()
    first.join(3)
    second.join(3)
    assert sorted(results) == ["device-a", "device-b"]


def test_local_render_environment_retains_connection_without_requiring_network():
    base = {
        "AUTORESEARCH_PROXY_REQUIRED": "1",
        "AUTORESEARCH_CONNECTION_GATEWAY": "http://127.0.0.1:1",
        "HTTP_PROXY": "http://another-device:7890",
    }
    with connection_scope("disconnected-device"):
        env = connection_environment(base)
    assert env["AUTORESEARCH_CONNECTION_ID"] == "disconnected-device"
    assert "HTTP_PROXY" not in env


def test_broker_resolution_scopes_codex_environment_and_rejects_stale_connection(
    routes, monkeypatch
):
    manager, alice, bob, alive = routes

    class Broker(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                proxy = manager.proxy_url(self.path.rsplit("/", 1)[1])
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"proxy_url": proxy}).encode())
            except ValueError:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Broker)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("AUTORESEARCH_PROXY_REQUIRED", "1")
    monkeypatch.setenv("AUTORESEARCH_CONNECTION_GATEWAY", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("HTTP_PROXY", "http://other-users-proxy:7890")
    monkeypatch.setenv("all_proxy", "socks5://other-users-proxy:7891")
    try:
        with connection_scope(alice):
            first = codex_environment()
        with connection_scope(bob):
            second = codex_environment()
        assert first["HTTP_PROXY"] == first["https_proxy"] == manager.proxy_url(alice)
        assert second["HTTP_PROXY"] == manager.proxy_url(bob)
        assert "all_proxy" not in first
        alive["alice-device"] = False
        with connection_scope(alice), pytest.raises(RuntimeError, match="断开"):
            codex_environment()
        with connection_scope(None), pytest.raises(RuntimeError, match="SSH"):
            codex_environment()
    finally:
        server.shutdown()
        server.server_close()


def test_only_internal_authenticated_headers_set_request_context(monkeypatch):
    monkeypatch.setenv("AUTORESEARCH_WORKER_TOKEN", "internal-worker")

    class Handler(ConnectionHandlerMixin, BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(current_connection()).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/"
        for token, expected in [("forged", None), ("internal-worker", "device-a")]:
            request = Request(base, headers={HEADER: "device-a", "X-AutoResearch-Worker": token})
            with urlopen(request, timeout=3) as response:
                assert json.load(response) == expected
    finally:
        server.shutdown()
        server.server_close()


def test_pipeline_keeps_connection_for_automatic_handoffs_and_rebinds_on_resume(app, monkeypatch):
    app.pipeline.close()
    with connection_scope("device-a"):
        first = app.pipeline.create({"direction": "first engineering fixture"})
    with connection_scope("device-b"):
        second = app.pipeline.create({"direction": "second engineering fixture"})
    captured = []
    monkeypatch.setattr(
        app.pipeline,
        "advance_search",
        lambda flow: captured.append((flow["id"], current_connection())),
    )
    app.pipeline.tick()
    assert captured == [(first["id"], "device-a"), (second["id"], "device-b")]
    app.pipeline.action(first["id"], "pause", {})
    with connection_scope("new-device"):
        app.pipeline.action(first["id"], "resume", {})
    assert app.pipeline.get(first["id"])["connection_id"] == "new-device"
    assert app.pipeline.get(second["id"])["connection_id"] == "device-b"
