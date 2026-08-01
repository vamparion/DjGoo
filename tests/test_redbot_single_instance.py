from __future__ import annotations

import asyncio
import builtins
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from launcher.djgoo_launcher import DjGooLauncher, Layout, process_exists
from tools import start_redbot_selector
from tools.start_redbot_selector import (
    CONSOLE_FLAG,
    DUPLICATE_EXIT_CODE,
    RedbotAlreadyRunning,
    SingleInstance,
    configure_managed_lavalink,
    duplicate_instance_message,
    install_audio_runtime_patch,
    redbot_lock_path,
)


def launcher_without_tk(tmp_path: Path) -> DjGooLauncher:
    launcher = object.__new__(DjGooLauncher)
    launcher.layout = Layout(tmp_path)
    launcher._requested_desired = None
    launcher._requested_at = 0.0
    return launcher


def test_redbot_pid_record_blocks_duplicate_console(tmp_path: Path) -> None:
    launcher = launcher_without_tk(tmp_path)
    launcher.layout.redbot_pid_file.parent.mkdir(parents=True)
    launcher.layout.redbot_pid_file.write_text(
        json.dumps({"pid": os.getpid()}),
        encoding="utf-8",
    )

    assert process_exists(os.getpid())
    assert launcher._redbot_or_stack_active() is True


def test_recent_start_request_blocks_console_before_pid_file_exists(tmp_path: Path) -> None:
    launcher = launcher_without_tk(tmp_path)
    launcher._requested_desired = True
    launcher._requested_at = time.monotonic()

    assert launcher._redbot_or_stack_active() is True


def test_live_supervisor_pid_blocks_console_before_redbot_starts(tmp_path: Path) -> None:
    launcher = launcher_without_tk(tmp_path)
    launcher.layout.supervisor_pid_file.parent.mkdir(parents=True)
    launcher.layout.supervisor_pid_file.write_text(
        json.dumps({"pid": os.getpid()}),
        encoding="utf-8",
    )

    assert launcher._redbot_or_stack_active() is True


def test_stale_desired_state_does_not_block_console_without_live_process(tmp_path: Path) -> None:
    launcher = launcher_without_tk(tmp_path)
    launcher.layout.state_file.parent.mkdir(parents=True)
    launcher.layout.state_file.write_text(
        json.dumps({"desired_running": True, "supervisor_pid": 99_999_999}),
        encoding="utf-8",
    )

    assert launcher._redbot_or_stack_active() is False


def test_redbot_single_instance_lock_rejects_second_owner(tmp_path: Path) -> None:
    first = SingleInstance(tmp_path / "redbot.lock")
    second = SingleInstance(tmp_path / "redbot.lock")
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.close()
        second.close()


def test_run_redbot_rejects_duplicate_before_touching_red_config(
    tmp_path: Path, monkeypatch
) -> None:
    owner = SingleInstance(redbot_lock_path(tmp_path))
    assert owner.acquire() is True
    monkeypatch.setattr(
        start_redbot_selector,
        "ensure_instance",
        lambda _root: (_ for _ in ()).throw(AssertionError("must not touch Red config")),
    )
    try:
        with pytest.raises(RedbotAlreadyRunning):
            start_redbot_selector.run_redbot(tmp_path)
    finally:
        owner.close()


def test_console_duplicate_error_stays_visible(monkeypatch) -> None:
    prompts: list[str] = []

    def duplicate(_root: Path) -> None:
        raise RedbotAlreadyRunning("already running")

    monkeypatch.setattr(start_redbot_selector, "run_redbot", duplicate)
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "")

    assert start_redbot_selector.main([CONSOLE_FLAG]) == DUPLICATE_EXIT_CODE
    assert prompts == ["\nPress Enter to close this window..."]


def test_duplicate_message_points_to_current_log(tmp_path: Path) -> None:
    message = duplicate_instance_message(tmp_path)

    assert "already using this package" in message
    assert str(tmp_path / "data" / "discordbot" / "core" / "logs" / "latest.log") in message


class _FakeSetting:
    def __init__(self, name: str, values: dict[str, object]) -> None:
        self.name = name
        self.values = values

    async def set(self, value: object) -> None:
        self.values[self.name] = value


class _FakeConfig:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def __getattr__(self, name: str) -> _FakeSetting:
        return _FakeSetting(name, self.values)


def test_red_audio_is_returned_to_managed_lavalink() -> None:
    cog = SimpleNamespace(config=_FakeConfig())

    asyncio.run(configure_managed_lavalink(cog))

    assert cog.config.values == {"use_external_lavalink": False}


def test_audio_initializer_forces_managed_mode_before_normal_startup() -> None:
    class FakeAudio:
        async def initialize(self) -> None:
            self.calls.append("original")

        def __init__(self) -> None:
            self.config = _FakeConfig()
            self.calls: list[str] = []

    audio_package = SimpleNamespace(Audio=FakeAudio)

    install_audio_runtime_patch(audio_package)
    instance = FakeAudio()
    asyncio.run(instance.initialize())

    assert instance.calls == ["original"]
    assert instance.config.values["use_external_lavalink"] is False


def test_audio_runtime_patch_is_idempotent() -> None:
    class FakeAudio:
        async def initialize(self) -> None:
            return None

    audio_package = SimpleNamespace(Audio=FakeAudio)

    install_audio_runtime_patch(audio_package)
    first_initialize = FakeAudio.initialize
    install_audio_runtime_patch(audio_package)

    assert FakeAudio.initialize is first_initialize


def test_run_redbot_cleans_stale_lavalink_before_loading_red(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(start_redbot_selector, "ensure_instance", lambda _root: calls.append("ensure"))
    monkeypatch.setattr(start_redbot_selector, "bind_red_data_manager", lambda _root: calls.append("bind"))
    monkeypatch.setattr(
        start_redbot_selector,
        "cleanup_lavalink_processes",
        lambda _root: calls.append("cleanup") or [],
    )
    monkeypatch.setattr(start_redbot_selector, "apply_runtime_patches", lambda: calls.append("patch"))
    monkeypatch.setattr(
        start_redbot_selector.runpy,
        "run_module",
        lambda *_args, **_kwargs: calls.append("red"),
    )

    start_redbot_selector.run_redbot(tmp_path)

    assert calls == ["ensure", "bind", "cleanup", "patch", "red"]
