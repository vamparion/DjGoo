from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001


def read_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def terminate_process(pid: int) -> bool:
    if pid <= 0 or not process_exists(pid):
        return True
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    return True


def wait_for_exit(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while process_exists(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def supervisor_identity(root: Path) -> tuple[int, bool, str]:
    state = read_json(root / "data" / "djgoo-supervisor-state.json") or {}
    record = read_json(root / "data" / "pids" / "supervisor.json") or {}
    try:
        pid = int(record.get("pid") or state.get("supervisor_pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    desired_running = bool(state.get("desired_running"))
    version = str(
        record.get("version")
        or state.get("supervisor_version")
        or ""
    ).strip()
    return pid, desired_running, version


def restart_stale_supervisor(
    root: Path,
    *,
    installed_version: str,
    runtime_python: Path,
    runtime_pythonw: Path,
    stack_script: Path,
    environment: Mapping[str, str],
    log: Callable[[str], None],
) -> bool:
    """Replace a supervisor that was loaded before the installed update.

    Incremental updates replace files on disk, but an already-running Python
    supervisor keeps executing its old imported code. Older DjGoo releases only
    sent ``stop`` during updates, leaving that process alive. A missing or
    different supervisor version therefore means the process must be shut down
    before the newly installed stack code can be used.
    """

    pid, desired_running, running_version = supervisor_identity(root)
    installed = str(installed_version or "").strip()
    if pid <= 0 or not process_exists(pid):
        return False
    if running_version and running_version == installed:
        return False

    label = running_version or "pre-versioned"
    log(
        f"Replacing stale DjGoo supervisor PID {pid} "
        f"({label}) with installed version {installed or 'unknown'}."
    )

    try:
        subprocess.run(
            [str(runtime_python), str(stack_script), "shutdown"],
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"Graceful supervisor shutdown did not complete: {exc}")

    if not wait_for_exit(pid, timeout=15.0):
        log(f"Forcing stale supervisor PID {pid} to exit.")
        if not terminate_process(pid) or not wait_for_exit(pid, timeout=5.0):
            raise RuntimeError(f"Could not stop stale DjGoo supervisor PID {pid}")

    (root / "data" / "pids" / "supervisor.json").unlink(missing_ok=True)
    (root / "data" / "djgoo-supervisor-state.json").unlink(missing_ok=True)

    if desired_running:
        subprocess.Popen(
            [str(runtime_pythonw), str(stack_script), "start"],
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        log("Started the stack with the newly installed supervisor code.")
    return True
