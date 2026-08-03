from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.app_layout import active_app_root, package_root, runtime_python


PROJECT_ROOT = package_root(Path(__file__).resolve().parents[1])
APP_ROOT = active_app_root(PROJECT_ROOT)
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tools.djgoo_portable_stack import configure_core, load_core
from tools.input_binding_adapter import install_input_binding
from tools.portable_environment import clean_subprocess_environment, portable_environment
from tools.recovery_policy import install_recovery_policy


SUPERVISOR_CONTRACT = 4
VOICE_LISTENER_MODULE = "voice.djgoo_voice_listener_bound"
PENDING_LAUNCHER_DIRECTORY = Path("tools") / "pending_launchers"


def schedule_pending_launcher_completion(
    project_root: Path = PROJECT_ROOT,
) -> bool:
    """Complete the one-time alpha.24-to-alpha.25 launcher migration."""

    root = project_root.resolve()
    pending = root / PENDING_LAUNCHER_DIRECTORY
    if not any(
        (pending / name).is_file()
        for name in ("DjGoo.exe", "DjGoo Mini Player.exe")
    ):
        return False
    helper = root / "tools" / "complete_launcher_update.py"
    if not helper.is_file():
        helper = APP_ROOT / "tools" / "complete_launcher_update.py"
    python = runtime_python(root, "host", windowed=True)
    if not helper.is_file() or not python.is_file():
        return False
    flags = (
        int(getattr(subprocess, "DETACHED_PROCESS", 0))
        | int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    )
    subprocess.Popen(
        [str(python), str(helper), "--root", str(root)],
        cwd=root,
        env=portable_environment(root, clean_subprocess_environment()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return True


def install_supervisor_contract(core: Any) -> None:
    original_snapshot = core.STATE.snapshot

    def snapshot() -> dict[str, object]:
        payload = dict(original_snapshot())
        payload["supervisor_contract"] = SUPERVISOR_CONTRACT
        payload["voice_listener_module"] = VOICE_LISTENER_MODULE
        payload["voice_binding_backend"] = "generalized-keyboard-mouse"
        payload["package_layout"] = "versioned-app-v1"
        payload["app_root"] = str(APP_ROOT)
        return payload

    core.STATE.snapshot = snapshot
    core._djgoo_supervisor_contract = SUPERVISOR_CONTRACT


def main() -> int:
    schedule_pending_launcher_completion()
    core = configure_core(
        load_core(),
        project_root=PROJECT_ROOT,
        app_root=APP_ROOT,
    )
    install_recovery_policy(core)
    install_input_binding(core)
    install_supervisor_contract(core)
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
