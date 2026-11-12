"""Resolve SSH forwards and keep one fail-closed proxy relay per connection."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import select
import shutil
import socket
import socketserver
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .connection_context import PROXY_KEYS


def tcp_sockets():
    rows = []
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        rows.append(
            {"local": fields[1], "remote": fields[2], "state": fields[3], "inode": fields[9]}
        )
    return rows


def process_sockets(pid):
    sockets = set()
    for entry in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            sockets.add(entry.readlink().as_posix())
        except OSError:
            pass
    return sockets


def process_identity(pid):
    process = Path("/proc") / str(pid)
    if process.joinpath("comm").read_text().strip() != "sshd":
        raise ValueError("SSH connection is no longer available")
    return process.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]


def ssh_forward(peer, destination_port):
    if peer[0] != "127.0.0.1" or not Path("/proc/net/tcp").exists():
        return None
    rows = tcp_sockets()
    source = f"0100007F:{peer[1]:04X}"
    destination = f"0100007F:{destination_port:04X}"
    inodes = {
        row["inode"]
        for row in rows
        if row["state"] == "01" and row["local"] == source and row["remote"] == destination
    }
    if not inodes:
        return None
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            identity = process_identity(process.name)
            sockets = process_sockets(process.name)
            if not any(f"socket:[{inode}]" in sockets for inode in inodes):
                continue
            forwards = [
                row
                for row in rows
                if row["state"] == "0A"
                and row["local"].startswith("0100007F:")
                and f"socket:[{row['inode']}]" in sockets
            ]
            if len(forwards) != 1:
                return None
            return {
                "pid": int(process.name),
                "started": identity,
                "port": int(forwards[0]["local"].split(":")[1], 16),
                "inode": forwards[0]["inode"],
            }
        except (OSError, ValueError, IndexError):
            continue
    return None


def forward_alive(forward):
    try:
        return process_identity(forward["pid"]) == forward[
            "started"
        ] and f"socket:[{forward['inode']}]" in process_sockets(forward["pid"])
    except (OSError, ValueError):
        return False


def check_chatgpt_proxy(proxy_url):
    address = urlsplit(proxy_url)
    with socket.create_connection((address.hostname, address.port), timeout=10) as connection:
        connection.sendall(b"CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n")
        header = b""
        while b"\r\n\r\n" not in header and len(header) < 8192:
            content = connection.recv(1024)
            if not content:
                break
            header += content
    status = header.split(b"\r\n", 1)[0].split()
    if len(status) < 2 or status[1] != b"200":
        code = status[1].decode(errors="replace") if len(status) >= 2 else "连接关闭"
        raise ValueError(f"本机代理未能建立 ChatGPT 连接，返回 {code}。请检查代理端口和节点。")


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        forward = self.server.forward
        if not forward_alive(forward):
            self.request.sendall(
                b"HTTP/1.1 502 SSH tunnel disconnected\r\nContent-Length: 0\r\n\r\n"
            )
            return
        try:
            with socket.create_connection(("127.0.0.1", forward["port"]), timeout=10) as upstream:
                upstream.settimeout(None)
                sockets = [self.request, upstream]
                while sockets:
                    readable, _, _ = select.select(sockets, [], [], 30)
                    if not readable and not forward_alive(forward):
                        return
                    for source in readable:
                        target = upstream if source is self.request else self.request
                        data = source.recv(65536)
                        if data:
                            target.sendall(data)
                        else:
                            sockets.remove(source)
                            target.shutdown(socket.SHUT_WR)
        except OSError:
            return


class RelayServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False


class Connections:
    def __init__(self, *, enabled=None):
        self.enabled = (
            os.environ.get("AUTORESEARCH_CONNECTION_PROXY") == "1" if enabled is None else enabled
        )
        self.token = secrets.token_urlsafe(32)
        self.base_url = ""
        self.lock = threading.RLock()
        self.relays = {}

    def resolve(self, peer, port):
        if not self.enabled:
            return None
        forward = ssh_forward(peer, port)
        if forward is None:
            return None
        identity = json.dumps(forward, sort_keys=True)
        connection_id = hashlib.sha256((self.token + identity).encode()).hexdigest()
        with self.lock:
            if connection_id not in self.relays:
                server = RelayServer(("127.0.0.1", 0), RelayHandler)
                server.forward = forward
                entry = {"server": server, "forward": forward, "test": {"status": "idle"}}
                self.relays[connection_id] = entry
                threading.Thread(target=server.serve_forever, daemon=True).start()
        return connection_id

    def proxy_url(self, connection_id):
        with self.lock:
            entry = self.relays.get(connection_id)
            if entry is None or not forward_alive(entry["forward"]):
                raise ValueError("SSH 代理连接已断开，请重新连接后继续任务。")
            return f"http://127.0.0.1:{entry['server'].server_address[1]}"

    def state(self, connection_id):
        with self.lock:
            entry = self.relays.get(connection_id)
            connected = entry is not None and forward_alive(entry["forward"])
            return {
                "enabled": self.enabled,
                "connected": connected,
                "message": "已识别当前 SSH 代理隧道。"
                if connected
                else "请使用包含 -R 反向转发的 SSH 命令连接本机代理。",
                "test": dict(entry["test"]) if entry else {"status": "idle"},
            }

    def test(self, connection_id, root):
        self.proxy_url(connection_id)
        with self.lock:
            entry = self.relays[connection_id]
            if entry["test"]["status"] != "running":
                entry["test"] = {"status": "running", "message": "正在验证 Codex 模型与命令工具。"}
                threading.Thread(target=self._test, args=(connection_id, root), daemon=True).start()
            return self.state(connection_id)

    def _test(self, connection_id, root):
        directory = root / "assets/output/workbench/runtime/network-tests" / secrets.token_hex(12)
        env = dict(os.environ)
        for key in PROXY_KEYS:
            env.pop(key, None)
        try:
            directory.mkdir(parents=True, mode=0o700)
            proof = secrets.token_hex(16)
            (directory / "proof.txt").write_text(proof)
            schema = directory / "schema.json"
            schema.write_text(
                json.dumps(
                    {
                        "type": "object",
                        "properties": {"proof": {"type": "string"}},
                        "required": ["proof"],
                        "additionalProperties": False,
                    }
                )
            )
            proxy = self.proxy_url(connection_id)
            check_chatgpt_proxy(proxy)
            env.update(
                {key: proxy for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
            )
            env.update(
                AUTORESEARCH_PROXY_REQUIRED="1",
                AUTORESEARCH_PROXY_URL=proxy,
                NO_PROXY="localhost,127.0.0.1,::1",
                no_proxy="localhost,127.0.0.1,::1",
            )
            cli = shutil.which(env.get("CODEX_CLI", "codex"))
            if not cli:
                raise ValueError("服务器尚未配置 Codex CLI。")
            output = directory / "response.json"
            command = [
                cli,
                "--ask-for-approval",
                "never",
                "--model",
                env.get("CODEX_MODEL", "gpt-6-astra"),
                "--config",
                'model_reasoning_effort="low"',
                "--cd",
                str(directory),
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--skip-git-repo-check",
                "--json",
                "--sandbox",
                "danger-full-access",
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                "-",
            ]
            with (directory / "codex.log").open("w") as log:
                result = subprocess.run(
                    command,
                    input="Engineering connectivity test. Use the native command tool to read proof.txt in the current directory and return its exact content as proof. Do not modify files or access other directories.",
                    text=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=directory,
                    timeout=300,
                    check=False,
                )
            if result.returncode or not output.is_file():
                raise ValueError("Codex 调用失败，请查看服务器连接测试日志。")
            if json.loads(output.read_text()).get("proof") != proof:
                raise ValueError("Codex 未通过真实文件读取校验，请查看服务器连接测试日志。")
            report = {"status": "passed", "message": "Codex 模型与命令工具调用成功。"}
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            report = {
                "status": "failed",
                "message": str(error)
                if not isinstance(error, subprocess.TimeoutExpired)
                else "Codex 连接测试超过 300 秒，请检查本机代理。",
            }
        report["log_directory"] = str(directory.relative_to(root))
        try:
            (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        except OSError:
            report["message"] += " 测试日志目录写入失败。"
        with self.lock:
            self.relays[connection_id]["test"] = report

    def close(self):
        for entry in self.relays.values():
            entry["server"].shutdown()
            entry["server"].server_close()
