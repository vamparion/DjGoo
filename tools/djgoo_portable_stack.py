from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).with_name("djgoo_stack_core.py")


def load_core():
    spec = importlib.util.spec_from_file_location("djgoo_stack_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load DjGoo supervisor core from {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def portable_windows_flags() -> int:
    """Use Windows flags that detach safely without requiring job breakaway rights."""

    if os.name != "nt":
        return 0
    return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


def spawn_portable_supervisor(core: Any) -> bool:
    """Start the supervisor through this adapter so portable overrides survive."""

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

    # A portable package must not be redirected to an old machine-wide DjGoo
    # Java setting. Prefer the bundled runtime whenever it is present.
    configured_java = Path(os.environ.get("DJGOO_JAVA", "java.exe"))
    core.JAVA = runtime_java if runtime_java.exists() else configured_java
    core.BOT_PYTHON = runtime_python
    core.VOICE_PYTHON = runtime_python
    core.PYTHONW = runtime_pythonw if runtime_pythonw.exists() else runtime_python
    core.REDBOT_SELECTOR = root / "tools" / "start_redbot_selector.py"
    core.LAVALINK_DIR = root / "data" / "discordbot" / "cogs" / "Audio"
    core.LAVALINK_JAR = core.LAVALINK_DIR / "Lavalink.jar"
    core.EVENT_LOG = core.LOG_DIR / "djgoo-events.jsonl"
    core.WINDOWS_DETACHED_FLAGS = portable_windows_flags()
    core.LOG = core.Logger()

    original_start_component = core.start_component

    def guarded_start_component(spec: Any, *, resume_playback: bool = False) -> bool:
        try:
            return bool(original_start_component(spec, resume_playback=resume_playback))
        except OSError as exc:
            core.LOG.event(
                "component.start_failed",
                component=getattr(spec, "name", "unknown"),
                command=getattr(spec, "command", []),
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

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

    core.start_component = guarded_start_component
    core.run_supervisor = guarded_run_supervisor
    core.spawn_supervisor = lambda: spawn_portable_supervisor(core)
    return core


def main() -> int:
    core = configure_core(load_core())
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
