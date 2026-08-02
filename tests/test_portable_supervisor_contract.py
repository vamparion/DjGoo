from __future__ import annotations

from tools.djgoo_portable_stack_entry import (
    SUPERVISOR_CONTRACT,
    VOICE_LISTENER_MODULE,
    install_supervisor_contract,
)


class State:
    def snapshot(self) -> dict[str, object]:
        return {"supervisor_pid": 123, "desired_running": True}


class Core:
    def __init__(self) -> None:
        self.STATE = State()


def test_portable_supervisor_reports_loaded_binding_contract() -> None:
    core = Core()
    install_supervisor_contract(core)

    snapshot = core.STATE.snapshot()
    assert snapshot["supervisor_contract"] == SUPERVISOR_CONTRACT
    assert snapshot["voice_listener_module"] == VOICE_LISTENER_MODULE
    assert core._djgoo_supervisor_contract == SUPERVISOR_CONTRACT
