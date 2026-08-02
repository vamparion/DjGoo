from __future__ import annotations

import time

from launcher.djgoo_host_control_center import DjGooHostControlCenter


def _control_center(*, state: dict, redbot_active: bool, requested=None):
    center = DjGooHostControlCenter.__new__(DjGooHostControlCenter)
    center._requested_desired = requested
    center._requested_at = time.monotonic()
    center._state = lambda: dict(state)
    center._redbot_process_active = lambda _state=None: redbot_active
    return center


def test_idle_supervisor_does_not_block_discord_configuration() -> None:
    center = _control_center(
        state={
            "desired_running": False,
            "supervisor_pid": 1234,
            "components": {},
        },
        redbot_active=False,
    )
    assert center._redbot_or_stack_active() is False


def test_actual_music_core_process_still_blocks_configuration() -> None:
    center = _control_center(
        state={"desired_running": False},
        redbot_active=True,
    )
    assert center._redbot_or_stack_active() is True


def test_recent_stop_request_overrides_stale_desired_running_state() -> None:
    center = _control_center(
        state={"desired_running": True},
        redbot_active=False,
        requested=False,
    )
    assert center._redbot_or_stack_active() is False


def test_recent_start_request_blocks_configuration() -> None:
    center = _control_center(
        state={"desired_running": False},
        redbot_active=False,
        requested=True,
    )
    assert center._redbot_or_stack_active() is True
