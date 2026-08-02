from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = int(os.environ.get("DJGOO_CONTROL_PORT", "47631"))
EXPECTED_SUPERVISOR_CONTRACT = 2


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


def live_supervisor_state(timeout: float = 0.75) -> dict[str, object] | None:
    """Read the live supervisor state even when its PID files are stale or absent."""

    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b'{"action":"status"}\n')
            with sock.makefile("rb") as stream:
                line = stream.readline(256_000)
        response = json.loads(line.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(response, dict) or response.get("ok") is not True:
        return None
    state = response.get("state")
    return dict(state) if isinstance(state, dict) else None


def _supervisor_sources(
    root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    state = read_json(root / "data" / "djgoo-supervisor-state.json") or {}
    record = read_json(root / "data" / "pids" / "supervisor.json") or {}
    live = live_supervisor_state() or {}
    return state, record, live


def _first_int(*values: object) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _first_float(*values: object) -> float:
    for value in values:
        try:
            parsed = float(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0.0


def supervisor_identity(root: Path) -> tuple[int, bool, str]:
    state, record, live = _supervisor_sources(root)
    pid = _first_int(
        live.get("supervisor_pid"),
        record.get("pid"),
        state.get("supervisor_pid"),
    )
    if "desired_running" in live:
        desired_running = bool(live.get("desired_running"))
    else:
        desired_running = bool(state.get("desired_running"))
    version = str(
        live.get("supervisor_version")
        or record.get("version")
        or state.get("supervisor_version")
        or ""
    ).strip()
    return pid, desired_running, version


def _supervisor_contract(root: Path) -> int:
    state, _, live = _supervisor_sources(root)
    return _first_int(
        live.get("supervisor_contract"),
        state.get("supervisor_contract"),
    )


def _supervisor_started_at(root: Path) -> float:
    state, _, live = _supervisor_sources(root)
    return _first_float(live.get("started_at"), state.get("started_at"))


def _installed_at(root: Path) -> float:
    payload = read_json(root / "data" / "installed-version.json") or {}
    return _first_float(payload.get("installed_at"))


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
    """Replace a supervisor loaded before the installed update.

    Older incremental updaters could leave the background supervisor alive while
    replacing its source files. The live process then kept the old listener in
    memory and rejected newly bindable buttons such as F5 or mouse buttons. This
    check uses the control socket as the authority when PID files are missing,
    and requires the current portable supervisor capability contract.
    """

    pid, desired_running, running_version = supervisor_identity(root)
    installed = str(installed_version or "").strip()
    if pid <= 0 or not process_exists(pid):
        return False

    contract = _supervisor_contract(root)
    started_at = _supervisor_started_at(root)
    installed_at = _installed_at(root)
    started_before_install = bool(
        started_at > 0
        and installed_at > 0
        and started_at + 0.5 < installed_at
    )
    version_is_current = bool(running_version and running_version == installed)
    contract_is_current = contract >= EXPECTED_SUPERVISOR_CONTRACT

    if version_is_current and contract_is_current and not started_before_install:
        return False

    reasons: list[str] = []
    if not running_version:
        reasons.append("pre-versioned")
    elif not version_is_current:
        reasons.append(f"version {running_version}")
    if not contract_is_current:
        reasons.append(f"contract {contract or 'missing'}")
    if started_before_install:
        reasons.append("started before the installed update")
    reason = ", ".join(reasons) or "stale code"

    log(
        f"Replacing stale DjGoo supervisor PID {pid} ({reason}) "
        f"with installed version {installed or 'unknown'}."
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
