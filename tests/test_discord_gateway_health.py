from types import SimpleNamespace

from pathlib import Path

import pytest

from local_cogs.djgoowelcome.djgoowelcome import (
    DjGooWelcome,
    discord_gateway_connected,
    resolve_command_queue_path,
)


class Bot:
    def __init__(self, ready: bool, closed: bool) -> None:
        self._ready = ready
        self.shards = {0: SimpleNamespace(is_closed=lambda: closed)}

    def is_ready(self) -> bool:
        return self._ready


def test_open_shard_is_connected() -> None:
    assert discord_gateway_connected(Bot(True, False))


def test_closed_shard_is_not_connected_even_when_ready_flag_is_stale() -> None:
    assert not discord_gateway_connected(Bot(True, True))


def test_legacy_websocket_shape_is_supported() -> None:
    bot = Bot(True, False)
    bot.shards = {0: SimpleNamespace(ws=SimpleNamespace(closed=False))}
    assert discord_gateway_connected(bot)


@pytest.mark.asyncio
async def test_disconnect_event_is_authoritative_until_gateway_resumes() -> None:
    cog = object.__new__(DjGooWelcome)
    cog._discord_gateway_connected = True

    await cog.on_shard_disconnect(0)
    assert cog._discord_gateway_connected is False

    await cog.on_shard_resumed(0)
    assert cog._discord_gateway_connected is True


def test_installed_host_ignores_stale_absolute_queue_path(tmp_path: Path) -> None:
    stale = Path("C:/old/source/data/voice-command-queue.jsonl")
    assert resolve_command_queue_path(
        tmp_path, stale, "voice-command-queue.jsonl", native_host=True
    ) == tmp_path / "data" / "voice-command-queue.jsonl"


def test_developer_mode_keeps_configured_queue_path(tmp_path: Path) -> None:
    configured = tmp_path / "custom.jsonl"
    assert resolve_command_queue_path(
        tmp_path, configured, "voice-command-queue.jsonl", native_host=False
    ) == configured
