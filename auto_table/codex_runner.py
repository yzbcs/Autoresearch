"""Run the same local Codex CLI as the other modules, with task-scoped artifacts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from workbench.connection_context import codex_environment
from auto_writing.web.serve import codex_timeout_seconds, resolve_codex_cli


class Cancelled(RuntimeError):
    pass


class Job:
    def __init__(self):
        import threading

        self.cancelled = threading.Event()
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("已停止当前任务，产物已保留，可继续。")

    def set_process(self, process):
        with self.lock:
            self.process = process
            if process and self.cancelled.is_set() and process.poll() is None:
                process.terminate()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()


def invoke(prompt: str, schema: Path, directory: Path, log_dir: Path, name: str, job: Job) -> dict:
    job.check()
    cli = resolve_codex_cli()
    log_dir.mkdir(parents=True, exist_ok=True)
    result_file = log_dir / f"{name}.response.json"
    result_file.unlink(missing_ok=True)
    (log_dir / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
    command = [
        str(cli),
        "--ask-for-approval",
        "never",
        "--cd",
        str(directory),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(result_file),
        "-",
    ]
    if os.environ.get("CODEX_IGNORE_USER_CONFIG", "1") == "1":
        command.insert(command.index("exec") + 1, "--ignore-user-config")
    if model := os.environ.get("CODEX_MODEL"):
        command[1:1] = ["--model", model]
    if effort := os.environ.get("CODEX_REASONING_EFFORT"):
        command[1:1] = ["--config", f'model_reasoning_effort="{effort}"']
    log_path = log_dir / f"{name}.log"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("command=" + json.dumps(command) + "\ncwd=" + str(directory) + "\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=codex_environment(),
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        job.set_process(process)
        try:
            process.communicate(input=prompt, timeout=codex_timeout_seconds(False))
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise RuntimeError("Codex 超时，已保留日志，可继续或修改要求后重新设计。") from error
        finally:
            job.set_process(None)
            log.write(f"\nexit_status={process.returncode}\n")
    job.check()
    if process.returncode:
        raise RuntimeError(f"Codex 退出码 {process.returncode}，请查看 {name}.log。")
    if not result_file.is_file():
        raise RuntimeError("Codex 没有返回结构化结果，请查看运行日志。")
    value = json.loads(result_file.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Codex 返回的结果必须为 JSON 对象。")
    return value
