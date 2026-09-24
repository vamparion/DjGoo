from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).with_name("djgoo_stack_core.py")
LAVALINK_HOST = "::1"
LAVALINK_PORT = 2333


def load_core():
    spec = importlib.util.spec_from_file_location("djgoo_stack_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load DjGoo supervisor core from {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def portable_windows_flags() -> int:
    """Run background components without visible Windows console windows."""

    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _process_cmdline(process: Any) -> list[str]:
    try:
        return [str(part) for part in process.cmdline()]
    except (psutil.Error, OSError, TypeError):
        return []


def _process_cwd(process: Any) -> Path | None:
    try:
        return Path(str(process.cwd())).resolve()
    except (psutil.Error, OSError, TypeError, ValueError):
        return None


def _process_matches_spec(process: Any, spec: Any) -> bool:
    cmdline = " ".join(_process_cmdline(process)).lower()
    if not cmdline:
        return False
    return all(str(marker).lower() in cmdline for marker in tuple(spec.command_markers))


def _lavalink_directory(project_root: Path) -> Path:
    return (
        project_root.resolve()
        / "data"
        / "discordbot"
        / "cogs"
        / "Audio"
    ).resolve()


def _process_is_package_lavalink(process: Any, project_root: Path) -> bool:
    command = " ".join(_process_cmdline(process)).lower()
    if "lavalink.jar" not in command:
        return False

    root = project_root.resolve()
    if str(root).lower() in command:
        return True

    return _process_cwd(process) == _lavalink_directory(root)


def _connection_port(connection: Any) -> int | None:
    local_address = getattr(connection, "laddr", None)
    value = getattr(local_address, "port", None)
    if value is None and isinstance(local_address, (tuple, list)) and len(local_address) >= 2:
        value = local_address[1]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _process_listens_on(process: Any, port: int) -> bool:
    try:
        connection_reader = getattr(process, "net_connections", None)
        if connection_reader is None:
            connection_reader = process.connections
        connections = connection_reader(kind="tcp")
    except (psutil.Error, OSError, AttributeError):
        return False

    for connection in connections:
        status = str(getattr(connection, "status", "")).upper()
        if _connection_port(connection) == int(port) and status in {
            str(psutil.CONN_LISTEN).upper(),
            "LISTEN",
        }:
            return True
    return False


def _processes_listening_on(port: int) -> list[Any]:
    listeners: list[Any] = []
    for process in psutil.process_iter():
        try:
            if int(process.pid) == os.getpid():
                continue
            if _process_listens_on(process, port):
                listeners.append(process)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return listeners


def _lavalink_port_ready(timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((LAVALINK_HOST, LAVALINK_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _matching_processes(spec: Any) -> list[Any]:
    matches: list[Any] = []
    for process in psutil.process_iter():
        try:
            if int(process.pid) == os.getpid():
                continue
            if _process_matches_spec(process, spec):
                matches.append(process)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return matches


def _matching_package_lavalink_processes(project_root: Path) -> list[Any]:
    matches: list[Any] = []
    for process in psutil.process_iter():
        try:
            if int(process.pid) == os.getpid():
                continue
            if _process_is_package_lavalink(process, project_root):
                matches.append(process)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return matches


def _process_age(process: Any) -> float:
    try:
        return float(process.create_time())
    except (psutil.Error, OSError, TypeError, ValueError):
        return float("inf")


def _oldest_process(processes: list[Any]) -> Any | None:
    if not processes:
        return None
    return min(processes, key=_process_age)


def _terminate_process_tree(process: Any) -> None:
    try:
        children = process.children(recursive=True)
    except psutil.Error:
        children = []

    targets = [*reversed(children), process]
    for target in targets:
        try:
            target.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=5)
    for target in alive:
        try:
            target.kill()
        except psutil.Error:
            pass


def _adopt_lavalink_listener(core: Any, spec: Any) -> bool:
    matches = _matching_package_lavalink_processes(core.PROJECT_ROOT)
    exact_listeners = [
        process for process in matches if _process_listens_on(process, LAVALINK_PORT)
    ]

    if exact_listeners:
        candidates = exact_listeners
        reason = "matching-lavalink-listener"
    elif matches and _lavalink_port_ready():
        candidates = matches
        reason = "reachable-lavalink-fallback"
    else:
        return False

    listener = _oldest_process(candidates)
    if listener is None:
        return False

    core.write_component_record(spec, listener)
    core.LOG.event(
        "component.adopted",
        component=spec.name,
        pid=int(listener.pid),
        reason=reason,
    )

    for duplicate in _matching_package_lavalink_processes(core.PROJECT_ROOT):
        if int(duplicate.pid) == int(listener.pid):
            continue
        core.LOG.event(
            "component.duplicate_stop",
            component=spec.name,
            pid=int(duplicate.pid),
            reason="listener-already-owned",
        )
        _terminate_process_tree(duplicate)
    return True


def _guard_lavalink_start(core: Any, spec: Any) -> bool | None:
    """Return True/False to handle Lavalink startup, or None to start normally."""

    if _adopt_lavalink_listener(core, spec):
        return True

    listeners = _processes_listening_on(LAVALINK_PORT)
    if not listeners:
        return None

    core.LOG.event(
        "component.port_in_use",
        component=spec.name,
        port=LAVALINK_PORT,
        owners=[
            {
                "pid": int(getattr(process, "pid", 0)),
                "cmdline": " ".join(_process_cmdline(process)),
                "cwd": str(_process_cwd(process) or ""),
            }
            for process in listeners
        ],
        reason="lavalink-port-owned-by-other-process",
    )
    return False


def _portable_lavalink_ready(core: Any) -> bool:
    record = core.component_record("lavalink")
    if not record:
        return False
    try:
        pid = int(record.get("pid") or 0)
        process = psutil.Process(pid)
        create_time = float(process.create_time())
        recorded_create_time = float(record.get("create_time") or 0)
    except (psutil.Error, OSError, TypeError, ValueError):
        return False
    if recorded_create_time and abs(create_time - recorded_create_time) > 1.0:
        return False

    if not _process_is_package_lavalink(process, core.PROJECT_ROOT):
        return False
    if _process_listens_on(process, LAVALINK_PORT):
        return True
    if not _lavalink_port_ready():
        return False

    oldest = _oldest_process(_matching_package_lavalink_processes(core.PROJECT_ROOT))
    return oldest is not None and int(oldest.pid) == pid


def _lavalink_client_ready(core: Any, expected_pid: int) -> bool:
    heartbeat = core.read_json(core.health_path("lavalink-client"))
    if not heartbeat:
        return False
    try:
        heartbeat_pid = int(heartbeat.get("pid") or 0)
        age = time.time() - float(heartbeat.get("timestamp") or 0)
    except (TypeError, ValueError):
        return False
    return (
        heartbeat_pid == expected_pid
        and -5.0 <= age <= 10.0
        and heartbeat.get("ready") is True
        and int(heartbeat.get("ready_node_count") or 0) >= 1
    )


def _portable_redbot_ready(core: Any) -> bool:
    record = core.component_record("redbot")
    heartbeat = core.read_json(core.health_path("redbot"))
    if not record or not heartbeat:
        return False
    try:
        expected_pid = int(record.get("pid") or 0)
        heartbeat_pid = int(heartbeat.get("pid") or 0)
        age = time.time() - float(heartbeat.get("timestamp") or 0)
    except (TypeError, ValueError):
        return False
    if expected_pid <= 0 or heartbeat_pid != expected_pid:
        return False
    if heartbeat.get("ready") is not True:
        return False
    if heartbeat.get("audio_loaded") is not True or heartbeat.get("discord_ready") is not True:
        return False
    if not _portable_lavalink_ready(core):
        return False
    if not _lavalink_client_ready(core, expected_pid):
        return False

    max_age = 120.0 if heartbeat.get("event") == "redbot.ready" else 15.0
    return -5.0 <= age <= max_age


def spawn_portable_supervisor(core: Any) -> bool:
    executable = core.PYTHONW if core.PYTHONW.exists() else core.BOT_PYTHON
    if not executable.exists():
        executable = Path(sys.executable)

    core.COMPONENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = core.COMPONENT_LOG_DIR / "supervisor.out.log"
    stderr_path = core.COMPONENT_LOG_DIR / "supervisor.err.log"
    command = [str(executable), str(Path(__file__).resolve()), "supervise"]

    try:
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            subprocess.Popen(
                command,
                cwd=str(core.PROJECT_ROOT),
                env=os.environ.copy(),
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                creationflags=core.WINDOWS_DETACHED_FLAGS if os.name == "nt" else 0,
            )
    except OSError as exc:
        core.LOG.event(
            "supervisor.spawn_failed",
            command=command,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if core.control_request("status", timeout=0.35):
            return True
        time.sleep(0.1)

    core.LOG.event("supervisor.spawn_timeout", command=command)
    return False


def configure_core(core: Any, project_root: Path = PROJECT_ROOT) -> Any:
    root = project_root.resolve()
    runtime_python = root / "runtime" / "python" / "python.exe"
    runtime_pythonw = root / "runtime" / "python" / "pythonw.exe"
    runtime_java = root / "runtime" / "java" / "bin" / "java.exe"

    core.PROJECT_ROOT = root
    core.LOG_DIR = root / "logs"
    core.COMPONENT_LOG_DIR = core.LOG_DIR / "components"
    core.PID_DIR = root / "data" / "pids"
    core.HEALTH_DIR = root / "data" / "health"
    core.STATE_PATH = root / "data" / "djgoo-supervisor-state.json"
    core.LOCK_PATH = root / "data" / "djgoo-supervisor.lock"
    core.SUPERVISOR_PID_PATH = core.PID_DIR / "supervisor.json"

    configured_java = Path(os.environ.get("DJGOO_JAVA", "java.exe"))
    core.JAVA = runtime_java if runtime_java.exists() else configured_java
    core.BOT_PYTHON = runtime_python
    core.VOICE_PYTHON = runtime_python
    core.PYTHONW = runtime_pythonw if runtime_pythonw.exists() else runtime_python
    core.REDBOT_SELECTOR = root / "tools" / "start_redbot_selector.py"
    core.LAVALINK_DIR = _lavalink_directory(root)
    core.LAVALINK_JAR = core.LAVALINK_DIR / "Lavalink.jar"
    core.EVENT_LOG = core.LOG_DIR / "djgoo-events.jsonl"
    core.WINDOWS_DETACHED_FLAGS = portable_windows_flags()
    core.LOG = core.Logger()

    original_component_running = core.component_running
    original_terminate_component = core.terminate_component
    original_component_environment = core.component_environment
    original_start_component = core.start_component

    def portable_component_running(spec: Any) -> bool:
        if original_component_running(spec):
            return True
        if getattr(spec, "name", "") == "lavalink":
            return _adopt_lavalink_listener(core, spec)
        return False

    def portable_terminate_component(spec: Any, reason: str) -> None:
        if getattr(spec, "name", "") == "lavalink":
            leftovers = _matching_package_lavalink_processes(root)
        else:
            leftovers = _matching_processes(spec)
        original_terminate_component(spec, reason)
        for process in leftovers:
            try:
                if not process.is_running():
                    continue
            except psutil.Error:
                continue
            core.LOG.event(
                "component.orphan_stop",
                component=getattr(spec, "name", "unknown"),
                pid=int(process.pid),
                reason=reason,
            )
            _terminate_process_tree(process)
        core.pid_path(spec.name).unlink(missing_ok=True)
        core.health_path(spec.name).unlink(missing_ok=True)
        if getattr(spec, "name", "") == "redbot":
            core.health_path("lavalink-client").unlink(missing_ok=True)

    def portable_component_environment(resume_playback: bool = False) -> dict[str, str]:
        env = original_component_environment(resume_playback=resume_playback)
        component_name = str(getattr(core, "_djgoo_starting_component", "")).strip()
        if component_name:
            env["DJGOO_COMPONENT_NAME"] = component_name
        return env

    def guarded_start_component(spec: Any, *, resume_playback: bool = False) -> bool:
        previous_component = getattr(core, "_djgoo_starting_component", "")
        core._djgoo_starting_component = str(getattr(spec, "name", ""))
        if getattr(spec, "name", "") == "redbot":
            core.health_path("lavalink-client").unlink(missing_ok=True)
        try:
            if getattr(spec, "name", "") == "lavalink":
                guarded = _guard_lavalink_start(core, spec)
                if guarded is not None:
                    return guarded
            return bool(original_start_component(spec, resume_playback=resume_playback))
        except OSError as exc:
            core.LOG.event(
                "component.start_failed",
                component=getattr(spec, "name", "unknown"),
                command=getattr(spec, "command", []),
                error=f"{type(exc).__name__}: {exc}",
            )
            return False
        finally:
            core._djgoo_starting_component = previous_component

    original_run_supervisor = core.run_supervisor

    def guarded_run_supervisor() -> int:
        try:
            return int(original_run_supervisor())
        except BaseException as exc:
            core.LOG.event(
                "supervisor.crashed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return 1

    core.component_running = portable_component_running
    core.terminate_component = portable_terminate_component
    core.component_environment = portable_component_environment
    core.start_component = guarded_start_component
    core.lavalink_ready = lambda: _portable_lavalink_ready(core)
    core.redbot_ready = lambda: _portable_redbot_ready(core)
    core.run_supervisor = guarded_run_supervisor
    core.spawn_supervisor = lambda: spawn_portable_supervisor(core)
    return core


def install_supervisor_adapters(core: Any) -> None:
    """Install behavior that must also exist inside the spawned supervisor."""

    from tools.input_binding_adapter import install_input_binding
    from tools.recovery_policy import install_recovery_policy

    install_recovery_policy(core)
    install_input_binding(core)


def main() -> int:
    core = configure_core(load_core())
    install_supervisor_adapters(core)
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
