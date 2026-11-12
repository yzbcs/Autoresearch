"""One independent Codex CLI process per workflow action."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from workbench.connection_context import codex_environment

MODULE_ROOT = Path(__file__).resolve().parent


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def resolve_codex_cli() -> str:
    configured = os.environ.get("CODEX_CLI", "codex")
    executable = shutil.which(configured)
    if not executable:
        raise RuntimeError("找不到 Codex CLI，请安装并登录，或设置 CODEX_CLI。")
    return str(Path(executable).resolve())


class CodexRunner:
    def __init__(self, sandbox: str = "danger-full-access") -> None:
        self.sandbox = sandbox

    def invoke(
        self,
        prompt: str,
        workspace: Path,
        log_dir: Path,
        on_event: Callable[[dict], None],
    ) -> dict:
        log_dir.mkdir(parents=True, exist_ok=False)
        output = log_dir / "response.json"
        command = [
            resolve_codex_cli(),
            "--ask-for-approval",
            "never",
            "--search",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "--sandbox",
            self.sandbox,
            "--cd",
            str(workspace),
            "--output-schema",
            str(MODULE_ROOT / "schemas" / "action.schema.json"),
            "--output-last-message",
            str(output),
            "--model",
            os.environ.get("CODEX_MODEL", "gpt-5.6-sol"),
            "--config",
            "model_reasoning_effort="
            + json.dumps(os.environ.get("CODEX_REASONING_EFFORT", "xhigh")),
            "-",
        ]
        (log_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        record = {"command": command, "cwd": str(workspace), "started_at": utc_now()}
        try:
            with (log_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=workspace,
                    env=codex_environment(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                record["pid"] = process.pid
                (log_dir / "execution.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(prompt)
                process.stdin.close()
                lines: queue.Queue[str | None] = queue.Queue()

                def read_lines() -> None:
                    for line in process.stdout:
                        lines.put(line)
                    lines.put(None)

                threading.Thread(target=read_lines, daemon=True).start()
                interrupted = False
                with (log_dir / "events.jsonl").open("w", encoding="utf-8") as events:
                    while True:
                        if (workspace / "controller_stop_requested.json").exists() and not interrupted:
                            interrupted = True
                            if process.poll() is None:
                                # Stop only this CLI controller. Remote training is preserved.
                                process.terminate()
                        try:
                            line = lines.get(timeout=0.2)
                        except queue.Empty:
                            if process.poll() is not None:
                                break
                            continue
                        if line is None:
                            break
                        events.write(line)
                        events.flush()
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            on_event(event)
                record["exit_status"] = process.wait()
            if interrupted:
                raise ControllerInterrupted("控制器已停止；训练进程保持原状，继续前将核对在途执行与已有结果。")
            if record["exit_status"] != 0:
                raise RuntimeError(f"Codex CLI 退出码 {record['exit_status']}；日志：{log_dir}")
            if not output.is_file():
                raise RuntimeError(f"Codex 未返回结构化结果；日志：{log_dir}")
            response = json.loads(output.read_text(encoding="utf-8"))
            validate_response(response)
            return response
        except Exception as error:
            record["error"] = str(error)
            raise
        finally:
            record["finished_at"] = utc_now()
            (log_dir / "execution.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )


class ControllerInterrupted(RuntimeError):
    """The user stopped the CLI controller without terminating experiment processes."""


def validate_response(response: object) -> None:
    if not isinstance(response, dict):
        raise TypeError("Codex 响应必须是 JSON 对象。")
    if response.get("outcome") not in {"completed", "blocked", "paused", "waiting_review"}:
        raise ValueError("Codex 响应缺少有效 outcome。")
    if not isinstance(response.get("summary"), str) or not response["summary"].strip():
        raise ValueError("Codex 响应缺少本步骤的事实总结。")
    if response.get("next_action") not in {
        "design",
        "run",
        "diagnosis",
        "audit",
        "revision",
        "none",
    }:
        raise ValueError("Codex 响应包含未知 next_action。")
