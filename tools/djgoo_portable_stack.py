from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


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


def main() -> int:
    core = load_core()
    runtime_python = PROJECT_ROOT / "runtime" / "python" / "python.exe"
    runtime_pythonw = PROJECT_ROOT / "runtime" / "python" / "pythonw.exe"
    runtime_java = PROJECT_ROOT / "runtime" / "java" / "bin" / "java.exe"

    core.PROJECT_ROOT = PROJECT_ROOT
    core.LOG_DIR = PROJECT_ROOT / "logs"
    core.COMPONENT_LOG_DIR = core.LOG_DIR / "components"
    core.PID_DIR = PROJECT_ROOT / "data" / "pids"
    core.HEALTH_DIR = PROJECT_ROOT / "data" / "health"
    core.STATE_PATH = PROJECT_ROOT / "data" / "djgoo-supervisor-state.json"
    core.LOCK_PATH = PROJECT_ROOT / "data" / "djgoo-supervisor.lock"
    core.SUPERVISOR_PID_PATH = core.PID_DIR / "supervisor.json"
    core.JAVA = Path(os.environ.get("DJGOO_JAVA", str(runtime_java)))
    core.BOT_PYTHON = runtime_python
    core.VOICE_PYTHON = runtime_python
    core.PYTHONW = runtime_pythonw if runtime_pythonw.exists() else runtime_python
    core.REDBOT_SELECTOR = PROJECT_ROOT / "tools" / "start_redbot_selector.py"
    core.LAVALINK_DIR = PROJECT_ROOT / "data" / "discordbot" / "cogs" / "Audio"
    core.LAVALINK_JAR = core.LAVALINK_DIR / "Lavalink.jar"
    core.EVENT_LOG = core.LOG_DIR / "djgoo-events.jsonl"
    core.LOG = core.Logger()
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
