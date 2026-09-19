from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from voice.djgoo_playlists import DjGooPlaylists
from voice.mini_player_protocol import (
    CommandReceiptStore,
    MiniPlayerHistory,
    mini_player_command,
)
from voice.request_ledger import RequestLedger


def test_mini_player_command_has_durable_correlation_id() -> None:
    item = mini_player_command(
        "mini_queue_remove",
        payload={"track_ids": ["track-1"]},
    )

    assert item["source"] == "mini_player"
    assert item["protocol"] == 2
    assert item["command_id"]
    assert item["payload"] == {"track_ids": ["track-1"]}


def test_command_receipt_round_trip_and_failure_detection(tmp_path: Path) -> None:
    store = CommandReceiptStore(tmp_path / "acks")
    command_id = mini_player_command("mini_search")["command_id"]

    store.write(
        command_id,
        intent="mini_search",
        result={"status": "failed", "message": "No clean song matches found."},
    )

    receipt = store.read(command_id, consume=True)
    assert receipt is not None
    assert receipt["success"] is False
    assert receipt["result"]["message"] == "No clean song matches found."
    assert store.read(command_id) is None


def test_history_dedupes_repeated_track_start_events(tmp_path: Path) -> None:
    history = MiniPlayerHistory(tmp_path / "history.json")
    track = {
        "id": "same-track",
        "title": "Sandstorm",
        "artist": "Darude",
        "uri": "https://example.test/sandstorm",
        "duration_seconds": 225,
    }

    history.add(track, mode="RADIO", station="Sandstorm radio")
    history.add(track, mode="RADIO", station="Sandstorm radio")

    assert len(history.entries()) == 1


def test_playlist_creation_and_rich_duplicate_prevention(tmp_path: Path) -> None:
    playlists = DjGooPlaylists(tmp_path / "playlists.json")
    name, created = playlists.create("80s")
    track = {
        "title": "Africa",
        "artist": "Toto",
        "uri": "https://example.test/africa",
        "duration_seconds": 295,
        "artwork_url": "https://example.test/africa.jpg",
    }

    first = playlists.add_track(name, track)
    second = playlists.add_track("my 80s playlist", track)

    assert created is True
    assert first.added is True
    assert second.added is False
    assert playlists.summaries()[0]["tracks"][0]["artist"] == "Toto"


def test_request_ledger_snapshot_can_be_restored_for_queue_undo(tmp_path: Path) -> None:
    ledger = RequestLedger(tmp_path / "requests.json")
    ledger.add(
        123,
        track_key="track-key",
        title="Requested song",
        timing="next",
        requester_name="Player",
    )
    snapshot = ledger.entries(123)

    ledger.replace_entries(123, [])
    assert ledger.entries(123) == []
    ledger.replace_entries(123, snapshot)

    assert ledger.entries(123)[0]["requester_name"] == "Player"


def test_queue_snapshot_uses_stable_ids_and_separates_request_lane(monkeypatch) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module

    requested = SimpleNamespace(title="Requested", uri="u:requested")
    automatic = SimpleNamespace(title="Automatic", uri="u:automatic")
    player = SimpleNamespace(queue=[requested, automatic], current=None)
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)

    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    bridge._queue_item_ids = {}
    bridge.stations = SimpleNamespace(get_active=lambda _guild_id: {"name": "Rock radio"})
    bridge.request_ledger = SimpleNamespace(
        entries=lambda _guild_id: [
            {
                "track_key": "u:requested",
                "requester_name": "Player",
                "requester_id": 42,
                "timing": "next",
            }
        ]
    )
    bridge._track_key = lambda track: track.uri
    bridge._track_data = lambda track: {
        "title": track.title,
        "uri": track.uri,
        "duration_seconds": "200",
    }

    first = bridge._queue_snapshot(123)
    second = bridge._queue_snapshot(123)

    assert first[0]["request_type"] == "request"
    assert first[0]["requester"] == "Player"
    assert first[1]["request_type"] == "radio"
    assert first[0]["id"] == second[0]["id"]


def test_receipt_pruning_keeps_current_and_removes_old(tmp_path: Path) -> None:
    store = CommandReceiptStore(tmp_path / "acks")
    old_id = mini_player_command("skip")["command_id"]
    current_id = mini_player_command("skip")["command_id"]
    old_path = store.write(old_id, intent="skip", result="Skipped")
    current_path = store.write(current_id, intent="skip", result="Skipped")
    assert old_path is not None and current_path is not None
    old_timestamp = time.time() - 100
    old_path.touch()
    old_path.write_text(
        json.dumps({"completed_at": old_timestamp}),
        encoding="utf-8",
    )
    import os

    os.utime(old_path, (old_timestamp, old_timestamp))

    store.prune(max_age_seconds=50)

    assert not old_path.exists()
    assert current_path.exists()


def test_mini_player_lock_prevents_competing_windows(tmp_path: Path) -> None:
    from launcher.djgoo_overlay import SingleMiniPlayer

    first = SingleMiniPlayer(tmp_path / "mini-player.lock")
    second = SingleMiniPlayer(tmp_path / "mini-player.lock")
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        second.close()
        first.close()

    replacement = SingleMiniPlayer(tmp_path / "mini-player.lock")
    try:
        assert replacement.acquire() is True
    finally:
        replacement.close()


@pytest.mark.asyncio
async def test_queue_reorder_and_remove_use_stable_track_ids(monkeypatch) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module

    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    audio = object()
    bridge.bot = SimpleNamespace(
        get_cog=lambda name: audio if name == "Audio" else None
    )
    bridge._context = lambda: SimpleNamespace(guild=SimpleNamespace(id=42))
    bridge._queue_item_ids = {}
    bridge._queue_undo = {}
    bridge.request_ledger = SimpleNamespace(
        entries=lambda _guild_id: [],
        consume=lambda _guild_id, _track_key: None,
    )
    bridge._persist_player_state = lambda *_args, **_kwargs: None
    bridge._track_key = lambda track: track.uri
    tracks = [
        SimpleNamespace(title="First", uri="track:first"),
        SimpleNamespace(title="Second", uri="track:second"),
        SimpleNamespace(title="Third", uri="track:third"),
    ]
    player = SimpleNamespace(queue=list(tracks), current=None)
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)
    track_ids = [bridge._stable_track_id(track) for track in tracks]

    reordered = await bridge._handle_mini_intent(
        {
            "intent": "mini_queue_reorder",
            "payload": {"track_ids": [track_ids[2], track_ids[0], track_ids[1]]},
        }
    )
    removed = await bridge._handle_mini_intent(
        {
            "intent": "mini_queue_remove_many",
            "payload": {"track_ids": [track_ids[0]]},
        }
    )

    assert reordered["status"] == "completed"
    assert [track.title for track in player.queue] == ["Third", "Second"]
    assert removed == {
        "status": "completed",
        "message": "Removed 1 queued track(s).",
    }


@pytest.mark.asyncio
async def test_queue_shuffle_includes_playlist_and_automatic_tracks(monkeypatch) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module

    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    audio = object()
    bridge.bot = SimpleNamespace(
        get_cog=lambda name: audio if name == "Audio" else None
    )
    bridge._context = lambda: SimpleNamespace(guild=SimpleNamespace(id=42))
    bridge._queue_undo = {}
    bridge.request_ledger = SimpleNamespace(entries=lambda _guild_id: [])
    bridge._persist_player_state = lambda *_args, **_kwargs: None
    tracks = [
        SimpleNamespace(title="Playlist One"),
        SimpleNamespace(title="Playlist Two"),
        SimpleNamespace(title="Automatic Radio"),
    ]
    player = SimpleNamespace(queue=list(tracks), current=None)
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)
    monkeypatch.setattr(module.random, "shuffle", lambda values: values.reverse())

    result = await bridge._handle_mini_intent({"intent": "mini_queue_shuffle"})

    assert result == {
        "status": "completed",
        "message": "Shuffled 3 queued tracks.",
    }
    assert [track.title for track in player.queue] == [
        "Automatic Radio",
        "Playlist Two",
        "Playlist One",
    ]
    assert bridge._queue_undo[42]["queue"] == tracks


@pytest.mark.asyncio
async def test_playlist_management_does_not_require_a_voice_member(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module
    from voice.mini_player_protocol import MiniPlayerHistory
    from voice.now_playing_state import NowPlayingState

    guild_id = 42
    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    bridge.bot = SimpleNamespace(guilds=[SimpleNamespace(id=guild_id)])
    bridge.playlists = DjGooPlaylists(tmp_path / "playlists.json")
    bridge.mini_history = MiniPlayerHistory(tmp_path / "history.json")
    bridge.now_playing = NowPlayingState(tmp_path / "now-playing.json")
    bridge._queue_item_ids = {}
    bridge.now_playing.publish(
        guild_id,
        {
            "current": {
                "id": "current-1",
                "title": "Current Song",
                "artist": "Current Artist",
                "uri": "https://example.test/current",
                "duration_seconds": 200,
            },
            "queue": [
                {
                    "id": "queued-1",
                    "title": "Queued Song",
                    "artist": "Queued Artist",
                    "uri": "https://example.test/queued",
                    "duration_seconds": 240,
                }
            ],
        },
    )
    bridge.mini_history.add(
        {
            "id": "history-1",
            "title": "History Song",
            "artist": "History Artist",
            "uri": "https://example.test/history",
            "duration_seconds": 180,
        },
        mode="REQUEST",
    )

    def no_live_player(_guild_id):
        raise module.PlayerNotFound

    monkeypatch.setattr(module.lavalink, "get_player", no_live_player)

    created = await bridge._handle_mini_intent(
        {"intent": "mini_playlist_create", "playlist": "KnockOut"}
    )
    added_current = await bridge._handle_mini_intent(
        {"intent": "mini_playlist_add_current", "playlist": "KnockOut"}
    )
    added_queue = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_add",
            "playlist": "KnockOut",
            "payload": {"track_ids": ["queued-1"]},
        }
    )
    added_history = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_add_history",
            "playlist": "KnockOut",
            "payload": {"history_ids": ["history-1"]},
        }
    )

    assert created["status"] == "completed"
    assert created["playlist"] == "knockout"
    assert added_current["added"] == 1
    assert added_queue["added"] == 1
    assert added_history["added"] == 1
    assert [
        track["title"] for track in bridge.playlists.get_tracks("KnockOut")
    ] == ["Current Song", "Queued Song", "History Song"]
    assert added_history["playlists"][0]["track_count"] == 3
