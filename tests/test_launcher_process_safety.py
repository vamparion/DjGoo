from __future__ import annotations

import json
import os
import time

from launcher.djgoo_launcher import DjGooLauncher, Layout, process_exists
from tools.start_redbot_selector import SingleInstance, duplicate_instance_message


def launcher_without_tk(tmp_path):
    launcher = object.__new__(DjGooLauncher)
    launcher.layout = Layout(tmp_path)
    launcher._requested_desired = None
    launcher._requested_at = 0.0
    return launcher


def test_redbot_pid_record_blocks_duplicate_console(tmp_path):
    launcher = launcher_without_tk(tmp_path)
    launcher.layout.redbot_pid_file.parent.mkdir(parents=True)
    launcher.layout.redbot_pid_file.write_text(
        json.dumps({"pid": os.getpid()}),
        encoding="utf-8",
    )

    assert process_exists(os.getpid())
    assert launcher._redbot_or_stack_active() is True


def test_recent_start_request_blocks_console_before_pid_file_exists(tmp_path):
    launcher = launcher_without_tk(tmp_path)
    launcher._requested_desired = True
    launcher._requested_at = time.monotonic()

    assert launcher._redbot_or_stack_active() is True


def test_redbot_single_instance_lock_rejects_second_owner(tmp_path):
    first = SingleInstance(tmp_path / "redbot.lock")
    second = SingleInstance(tmp_path / "redbot.lock")
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.close()
        second.close()


def test_duplicate_message_points_to_current_log(tmp_path):
    message = duplicate_instance_message(tmp_path)

    assert "already using this package" in message
    assert str(tmp_path / "data" / "discordbot" / "core" / "logs" / "latest.log") in message
