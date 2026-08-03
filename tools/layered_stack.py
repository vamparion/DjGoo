from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from tools import djgoo_portable_stack as legacy
from tools.app_layout import active_app_root, runtime_python, speech_runtime_ready
from tools.portable_environment import portable_environment


load_core = legacy.load_core


def host_speech_available(root: Path) -> bool:
    if speech_runtime_ready(root):
        return True
    # In-place alpha.24 migrations retain the original combined runtime.
    legacy_site = root / "runtime" / "python" / "Lib" / "site-packages"
    return (legacy_site / "faster_whisper").is_dir()


def _spawn_supervisor(core: Any, root: Path, app: Path) -> bool:
    executable = core.PYTHONW if core.PYTHONW.exists() else core.BOT_PYTHON
    script = app / "tools" / "djgoo_portable_stack_entry.py"
    if not executable.is_file() or not script.is_file():
        core.LOG.event(
            "supervisor.spawn_failed",
            error="layered runtime or entrypoint missing",
            executable=str(executable),
            script=str(script),
        )
        return False
    core.COMPONENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = core.COMPONENT_LOG_DIR / "supervisor.out.log"
    stderr_path = core.COMPONENT_LOG_DIR / "supervisor.err.log"
    command = [str(executable), str(script), "supervise"]
    try:
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            subprocess.Popen(
                command,
                cwd=root,
                env=portable_environment(root, os.environ),
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


def configure_core(
    core: Any,
    *,
    project_root: Path,
    app_root: Path | None = None,
) -> Any:
    root = project_root.resolve()
    app = (app_root or active_app_root(root)).resolve()
    core = legacy.configure_core(core, project_root=root)

    bot_python = runtime_python(root, "host")
    bot_pythonw = runtime_python(root, "host", windowed=True)
    core.BOT_PYTHON = bot_python
    core.VOICE_PYTHON = bot_python
    core.PYTHONW = bot_pythonw if bot_pythonw.is_file() else bot_python
    core.REDBOT_SELECTOR = app / "tools" / "start_redbot_selector.py"
    core.JAVA = root / "runtime" / "java" / "bin" / "java.exe"
    core.LAVALINK_DIR = root / "data" / "discordbot" / "cogs" / "Audio"
    core.LAVALINK_JAR = core.LAVALINK_DIR / "Lavalink.jar"

    original_build_specs = core.build_specs
    missing_logged = False

    def layered_specs():
        nonlocal missing_logged
        specs = list(original_build_specs())
        if host_speech_available(root):
            return specs
        filtered = [spec for spec in specs if getattr(spec, "name", "") != "voice"]
        if not missing_logged:
            core.LOG.event(
                "voice.optional_runtime_missing",
                action="install-from-host-control-center",
            )
            missing_logged = True
        return filtered

    core.build_specs = layered_specs
    core.spawn_supervisor = lambda: _spawn_supervisor(core, root, app)
    core._djgoo_app_root = app
    return core
