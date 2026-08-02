from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.djgoo_portable_stack import configure_core, load_core
from tools.input_binding_adapter import install_input_binding
from tools.recovery_policy import install_recovery_policy


SUPERVISOR_CONTRACT = 3
VOICE_LISTENER_MODULE = "voice.djgoo_voice_listener_bound"


def install_supervisor_contract(core: Any) -> None:
    """Expose the loaded supervisor capabilities in every state snapshot.

    A portable update can replace Python files while an older supervisor keeps
    running its already-imported code. The Control Center uses this contract to
    identify and replace that stale process, even when its PID files are missing
    or its version string happens to match the newly installed release.
    """

    original_snapshot = core.STATE.snapshot

    def snapshot() -> dict[str, object]:
        payload = dict(original_snapshot())
        payload["supervisor_contract"] = SUPERVISOR_CONTRACT
        payload["voice_listener_module"] = VOICE_LISTENER_MODULE
        payload["voice_binding_backend"] = "generalized-keyboard-mouse"
        return payload

    core.STATE.snapshot = snapshot
    core._djgoo_supervisor_contract = SUPERVISOR_CONTRACT


def main() -> int:
    core = configure_core(load_core())
    install_recovery_policy(core)
    install_input_binding(core)
    install_supervisor_contract(core)
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
