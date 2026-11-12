"""Carry the originating SSH connection through requests and background jobs."""

from __future__ import annotations

import contextvars
import hmac
import json
import os
import threading
from contextlib import contextmanager
from urllib.request import ProxyHandler, Request, build_opener

HEADER = "X-AutoResearch-Connection"
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_connection = contextvars.ContextVar("autoresearch_connection", default=None)


def current_connection() -> str | None:
    return _connection.get() or os.environ.get("AUTORESEARCH_CONNECTION_ID") or None


@contextmanager
def connection_scope(connection_id):
    token = _connection.set(connection_id)
    try:
        yield
    finally:
        _connection.reset(token)


def background_thread(*, target, args=(), kwargs=None, **options):
    context = contextvars.copy_context()
    return threading.Thread(
        target=context.run, args=(target, *args), kwargs=kwargs or {}, **options
    )


class ConnectionHandlerMixin:
    def handle_one_request(self):
        with connection_scope(None):
            return super().handle_one_request()

    def parse_request(self):
        parsed = super().parse_request()
        expected = os.environ.get("AUTORESEARCH_WORKER_TOKEN", "")
        if (
            parsed
            and expected
            and hmac.compare_digest(self.headers.get("X-AutoResearch-Worker", ""), expected)
        ):
            _connection.set(self.headers.get(HEADER) or None)
        return parsed


def connection_environment(base=None, *, require=False):
    env = dict(os.environ if base is None else base)
    connection_id = current_connection() or env.get("AUTORESEARCH_CONNECTION_ID")
    managed = env.get("AUTORESEARCH_PROXY_REQUIRED") == "1"
    if not managed and not connection_id:
        return env
    for key in PROXY_KEYS:
        env.pop(key, None)
    env.pop("AUTORESEARCH_PROXY_URL", None)
    env["AUTORESEARCH_CONNECTION_ID"] = connection_id or ""
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    if not require:
        return env
    if not connection_id:
        raise RuntimeError("请使用包含 -R 反向转发的 SSH 命令连接本机代理，再继续任务。")
    gateway = env.get("AUTORESEARCH_CONNECTION_GATEWAY", "")
    request = Request(
        gateway + "/api/internal/connection/" + connection_id,
        headers={"X-AutoResearch-Network": env.get("AUTORESEARCH_CONNECTION_TOKEN", "")},
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            proxy = json.load(response)["proxy_url"]
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError("发起任务的 SSH 代理连接已断开，请重新连接后继续任务。") from error
    env["AUTORESEARCH_PROXY_URL"] = proxy
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[key] = proxy
    return env


def codex_environment():
    return connection_environment(require=True)
