"""Isolated environment around the existing, unchanged AutoWriting compiler."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from auto_writing.web.serve import latex_timeout_seconds

from .upstream_runner import ProcessGroup, runtime_environment


def compile_latex(main, build, log, callback):
    build.mkdir(parents=True, exist_ok=True)
    result = build / "compile-result.json"
    result.unlink(missing_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).with_name("compile_worker.py")),
        str(main),
        str(build),
        str(log),
        str(result),
    ]
    with log.with_name("compiler-worker.log").open("w") as output:
        process = subprocess.Popen(
            command,
            cwd=main.parent,
            env=runtime_environment(),
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        group = ProcessGroup(process)
        callback(group)
        try:
            process.wait(timeout=latex_timeout_seconds() * 4 + 30)
        except subprocess.TimeoutExpired as error:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError("LaTeX 编译超时，请查看 compiler-worker.log。") from error
        finally:
            callback(None)
            # Also stop descendants if the worker was interrupted while waiting on TeX.
            group.terminate()
    if process.returncode or not result.is_file():
        raise RuntimeError("LaTeX 编译失败，请查看 compile.log / compiler-worker.log。")
    data = json.loads(result.read_text())
    return data["compiler"], Path(data["pdf"])
