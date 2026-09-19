from __future__ import annotations

import asyncio
import builtins
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from launcher.djgoo_launcher import DjGooLauncher, Layout, process_exists
from tools import start_redbot_selector
from tools.start_redbot_selector import (
    CONSOLE_FLAG,
    DUPLICATE_EXIT_CODE,
    LAVALINK_BIND_HOST,
    LAVALINK_HOST,
    LAVALINK_PASSWORD,
    LAVALINK_PORT,
    RedbotAlreadyRunning,
    SingleInstance,
    apply_bundled_java_environment,
    bundled_java_executable,
    configure_external_lavalink,
    duplicate_instance_message,
    install_audio_runtime_patch,
    monitor_lavalink_client,
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

    def duplicate(_root: Path, **_kwargs) -> None:
        raise RedbotAlreadyRunning("already running")

    monkeypatch.setattr(start_redbot_selector, "run_redbot", duplicate)
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "")

    assert start_redbot_selector.main([CONSOLE_FLAG]) == DUPLICATE_EXIT_CODE
    assert prompts == ["\nPress Enter to close this window..."]


def test_duplicate_message_points_to_current_log(tmp_path: Path) -> None:
    message = duplicate_instance_message(tmp_path)

    assert "already using this package" in message
    assert str(tmp_path / "data" / "discordbot" / "core" / "logs" / "latest.log") in message


class _FakeConfigNode:
    def __init__(self, values: dict[str, object], path: tuple[str, ...] = ()) -> None:
        self.values = values
        self.path = path

    def __getattr__(self, name: str) -> "_FakeConfigNode":
        return _FakeConfigNode(self.values, (*self.path, name))

    async def set(self, value: object) -> None:
        self.values[".".join(self.path)] = value


class _FakeConfig(_FakeConfigNode):
    def __init__(self) -> None:
        super().__init__({})


def test_bundled_java_environment_precedes_machine_path(tmp_path: Path, monkeypatch) -> None:
    java = bundled_java_executable(tmp_path)
    java.parent.mkdir(parents=True)
    java.write_bytes(b"")
    monkeypatch.setenv("PATH", os.pathsep.join(["machine-java", "other-bin"]))
    monkeypatch.delenv("JAVA_HOME", raising=False)

    resolved = apply_bundled_java_environment(tmp_path)

    assert resolved == java
    assert os.environ["JAVA_HOME"] == str(java.parents[1])
    assert os.environ["PATH"].split(os.pathsep)[0] == str(java.parent)


def test_red_audio_restores_original_external_ipv6_contract() -> None:
    config = _FakeConfig()
    cog = SimpleNamespace(config=config)

    asyncio.run(configure_external_lavalink(cog))

    assert config.values == {
        "use_external_lavalink": True,
        "host": "[::1]",
        "rest_port": LAVALINK_PORT,
        "ws_port": LAVALINK_PORT,
        "password": LAVALINK_PASSWORD,
        "secured_ws": False,
        "yaml.server.address": "::1",
        "yaml.server.port": LAVALINK_PORT,
        "yaml.lavalink.server.password": LAVALINK_PASSWORD,
    }
    assert LAVALINK_HOST == "[::1]"
    assert LAVALINK_BIND_HOST == "::1"
    assert f"ws://{LAVALINK_HOST}:{LAVALINK_PORT}" == "ws://[::1]:2333"


def test_audio_initializer_applies_external_settings_before_normal_startup(
    tmp_path: Path,
) -> None:
    class FakeTask:
        def done(self) -> bool:
            return False

    class FakeAudio:
        async def initialize(self) -> None:
            self.calls.append(("original", dict(self.config.values)))

        def __init__(self) -> None:
            self.config = _FakeConfig()
            self.calls: list[tuple[str, dict[str, object]]] = []
            self._djgoo_lavalink_health_task = FakeTask()

    audio_package = SimpleNamespace(Audio=FakeAudio)

    install_audio_runtime_patch(audio_package, tmp_path)
    instance = FakeAudio()
    asyncio.run(instance.initialize())

    assert instance.calls[0][0] == "original"
    settings_seen_by_original = instance.calls[0][1]
    assert settings_seen_by_original["use_external_lavalink"] is True
    assert settings_seen_by_original["host"] == "[::1]"
    assert settings_seen_by_original["yaml.server.address"] == "::1"


def test_audio_runtime_patch_is_idempotent(tmp_path: Path) -> None:
    class FakeAudio:
        async def initialize(self) -> None:
            return None

    audio_package = SimpleNamespace(Audio=FakeAudio)

    install_audio_runtime_patch(audio_package, tmp_path)
    first_initialize = FakeAudio.initialize
    install_audio_runtime_patch(audio_package, tmp_path)

    assert FakeAudio.initialize is first_initialize


def test_lavalink_health_uses_red_node_ready_state(tmp_path: Path, monkeypatch) -> None:
    class StopMonitor(Exception):
        pass

    nodes = [SimpleNamespace(ready=False), SimpleNamespace(ready=True)]
    fake_lavalink = SimpleNamespace(get_all_nodes=lambda: nodes)
    monkeypatch.setitem(sys.modules, "lavalink", fake_lavalink)
    heartbeats: list[tuple[str, dict[str, object]]] = []

    def capture(component: str, *, project_root: Path, fields: dict[str, object]) -> None:
        heartbeats.append((component, fields))

    async def stop_after_first(_seconds: float) -> None:
        raise StopMonitor

    monkeypatch.setattr(start_redbot_selector, "write_heartbeat", capture)
    monkeypatch.setattr(start_redbot_selector.asyncio, "sleep", stop_after_first)

    with pytest.raises(StopMonitor):
        asyncio.run(monitor_lavalink_client(tmp_path))

    assert heartbeats == [
        (
            "lavalink-client",
            {
                "ready": True,
                "node_count": 2,
                "ready_node_count": 1,
                "host": "[::1]",
                "port": 2333,
                "error": "",
            },
        )
    ]


def test_run_redbot_preserves_supervisor_owned_lavalink(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(start_redbot_selector, "ensure_instance", lambda _root: calls.append("ensure"))
    monkeypatch.setattr(start_redbot_selector, "bind_red_data_manager", lambda _root: calls.append("bind"))
    monkeypatch.setattr(
        start_redbot_selector,
        "apply_runtime_patches",
        lambda _root: calls.append("patch"),
    )
    monkeypatch.setattr(
        start_redbot_selector.runpy,
        "run_module",
        lambda *_args, **_kwargs: calls.append("red"),
    )

    start_redbot_selector.run_redbot(tmp_path, allow_interactive_setup=True)

    assert calls == ["ensure", "bind", "patch", "red"]
