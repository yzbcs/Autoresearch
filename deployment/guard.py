"""Project-local detached service guardian; adopts an existing workbench."""

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deployment"
LOGS = ROOT / "assets/logs/workbench"
RUNTIME = ROOT / "assets/output/workbench/runtime"


def gateway_state():
    """The account endpoint remains available before any user logs in."""
    try:
        with urlopen("http://127.0.0.1:8760/api/auth/session", timeout=3) as response:
            value = json.load(response)
        if "setup_required" in value and "authenticated" in value:
            return {"connected": True, "account_mode": True}
    except HTTPError as error:
        if error.code != 404:
            raise
    with urlopen("http://127.0.0.1:8760/api/service", timeout=3) as response:
        return json.load(response)


def log(message):
    print(f"{datetime.now().astimezone().isoformat()} {message}", flush=True)


def existing():
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
            if (
                b"-m" in args
                and b"workbench" in args
                and b"8760" in args
                and (entry / "cwd").resolve() == ROOT
            ):
                return int(entry.name)
        except (OSError, RuntimeError):
            continue
    return None


def port_open():
    with socket.socket() as sock:
        sock.settimeout(2)
        return sock.connect_ex(("127.0.0.1", 8760)) == 0


def recover_worker(pid):
    # Only recover a missing worker. A slow but living worker may be doing research.
    try:
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        if children:
            return
        state = gateway_state()
        if state.get("account_mode"):
            return
        if not state.get("connected") and not state.get("restarting"):
            request = Request(
                "http://127.0.0.1:8760/api/service/restart",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=5) as response:
                log(f"worker missing; recovery requested: HTTP {response.status}")
    except (OSError, ValueError) as error:
        log(f"worker check: {error}")


def supervise():
    LOGS.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "guard.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        (RUNTIME / "guard.pid").write_text(str(os.getpid()) + "\n")
        log(f"guardian started pid={os.getpid()}")
        child = None
        adopted = None
        while True:
            if child is not None and child.poll() is not None:
                log(f"workbench pid={child.pid} exit={child.returncode}; retry in 5 seconds")
                child = None
                time.sleep(5)
            pid = existing()
            if pid:
                if adopted != pid:
                    log(f"monitoring existing workbench pid={pid}")
                    (RUNTIME / "workbench.pid").write_text(str(pid) + "\n")
                    adopted = pid
                recover_worker(pid)
            elif child is not None:
                pass  # Launcher is still alive; never start a competing copy.
            elif port_open():
                log("port 8760 belongs to another process; waiting without replacing it")
            else:
                if adopted:
                    log(f"adopted workbench pid={adopted} disappeared; exit status unavailable")
                    adopted = None
                with (LOGS / "gateway.log").open("ab") as output:
                    os.fchmod(output.fileno(), 0o600)
                    child = subprocess.Popen(
                        ["bash", str(DEPLOY / "run-service.sh")],
                        cwd=ROOT,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=output,
                        start_new_session=True,
                    )
                log(f"workbench started pid={child.pid}")
                (RUNTIME / "workbench.pid").write_text(str(child.pid) + "\n")
            time.sleep(5)


def main():
    if sys.argv[1:] == ["--daemon"]:
        supervise()
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: bash deployment/start.sh (fixed shared service on port 8760)")
    LOGS.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (LOGS / "guard.log").open("ab") as output:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--daemon"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
    for _ in range(60):
        try:
            if gateway_state().get("connected"):
                print("AutoResearch account gateway is running in background on 127.0.0.1:8760.")
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise SystemExit("Guardian started; check assets/logs/workbench/guard.log for readiness.")


if __name__ == "__main__":
    main()
