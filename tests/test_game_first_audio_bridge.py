from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from local_cogs.djgoowelcome.game_first_audio_bridge import GameFirstDjGooAudioBridge
from local_cogs.djgoowelcome.remote_aware_bridge import RemoteAwareDjGooAudioBridge


@pytest.mark.asyncio
async def test_active_radio_play_uses_request_lane() -> None:
    bridge = object.__new__(GameFirstDjGooAudioBridge)
    audio = object()
    ctx = SimpleNamespace(guild=SimpleNamespace(id=42))
    bridge.bot = SimpleNamespace(get_cog=lambda name: audio if name == "Audio" else None)
    bridge._context = lambda: ctx
    bridge.stations = SimpleNamespace(
        get_active=lambda guild_id: {"name": "Balanced: rock", "seed": "balanced rock"}
    )
    bridge._resolve_play_queries = AsyncMock(return_value=["https://example.test/song"])
    bridge._queue_radio_request = AsyncMock(return_value="Queued request next")

    result = await bridge.handle(
        {"intent": "play", "query": "Sandstorm", "source": "voice"}
    )

    assert result == "Queued request next"
    bridge._queue_radio_request.assert_awaited_once_with(
        audio,
        ctx,
        "https://example.test/song",
        station_name="Balanced: rock",
    )


def test_request_detection_ignores_preexisting_radio_tracks() -> None:
    bridge = object.__new__(GameFirstDjGooAudioBridge)
    current = SimpleNamespace(track_identifier="current")
    old_radio = SimpleNamespace(track_identifier="old-radio")
    request = SimpleNamespace(track_identifier="request")
    player = SimpleNamespace(current=current, queue=[request, old_radio])

    assert bridge._new_track_from_player(
        player,
        {id(current), id(old_radio)},
    ) is request


def test_failed_enqueue_does_not_relabel_existing_radio_track() -> None:
    bridge = object.__new__(GameFirstDjGooAudioBridge)
    current = SimpleNamespace(track_identifier="current")
    old_radio = SimpleNamespace(track_identifier="old-radio")
    player = SimpleNamespace(current=current, queue=[old_radio])

    assert bridge._new_track_from_player(
        player,
        {id(current), id(old_radio)},
    ) is None


def test_bumped_track_is_classified_as_radio_request() -> None:
    bridge = object.__new__(GameFirstDjGooAudioBridge)
    bridge._radio_request_counts = {}
    track = SimpleNamespace(track_identifier="track-1", extras={"bumped": True})

    assert bridge._consume_radio_request(42, track) is True


def test_remembered_request_is_consumed_once() -> None:
    bridge = object.__new__(GameFirstDjGooAudioBridge)
    bridge._radio_request_counts = {42: Counter({"track-1": 1})}
    track = SimpleNamespace(track_identifier="track-1", extras={})

    assert bridge._consume_radio_request(42, track) is True
    assert bridge._consume_radio_request(42, track) is False


def test_remote_bridge_keeps_game_first_behavior() -> None:
    assert issubclass(RemoteAwareDjGooAudioBridge, GameFirstDjGooAudioBridge)


def test_panel_control_targets_the_connected_player() -> None:
    voice_channel = SimpleNamespace(id=56)
    owner = SimpleNamespace(id=99)
    guild = SimpleNamespace(
        id=42,
        owner=owner,
        me=None,
        voice_client=SimpleNamespace(channel=voice_channel),
    )
    bridge = object.__new__(RemoteAwareDjGooAudioBridge)
    bridge.bot = SimpleNamespace(guilds=[guild])
    bridge._best_text_channel = lambda selected: SimpleNamespace(id=77)
    bridge._context_for = lambda selected, author, channel: SimpleNamespace(
        guild=selected,
        author=author,
        channel=channel,
    )

    token = __import__("local_cogs.djgoowelcome.remote_aware_bridge", fromlist=["_CURRENT_COMMAND"])._CURRENT_COMMAND.set(
        {"source": "panel", "intent": "toggle_pause"}
    )
    try:
        context = bridge._context()
    finally:
        __import__("local_cogs.djgoowelcome.remote_aware_bridge", fromlist=["_CURRENT_COMMAND"])._CURRENT_COMMAND.reset(token)

    assert context.guild is guild
    assert context.author.id == owner.id
    assert context.author.voice.channel is voice_channel


@pytest.mark.asyncio
async def test_internal_play_invocation_bypasses_public_play_router() -> None:
    calls = []

    async def routed(_audio, _ctx, **_kwargs):
        calls.append("routed")

    async def original(_audio, _ctx, **kwargs):
        calls.append(("original", kwargs["query"]))

    command = SimpleNamespace(
        qualified_name="play",
        callback=routed,
        _djgoo_original_callback=original,
    )
    bridge = object.__new__(RemoteAwareDjGooAudioBridge)
    bridge.bot = SimpleNamespace(get_cog=lambda name: object() if name == "Audio" else None)
    ctx = SimpleNamespace(guild=SimpleNamespace(id=42), channel=SimpleNamespace(id=77))

    await bridge._invoke(command, ctx, query="https://example.test/track")

    assert calls == [("original", "https://example.test/track")]
