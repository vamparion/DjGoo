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

    assert first[0]["request_type"] == "manual"
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
async def test_resume_waits_for_audio_to_reconstruct_existing_player(
    monkeypatch,
) -> None:
    from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

    bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
    checks = iter((False, False, True))
    bridge._player_has_music = lambda _guild_id: next(checks)

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("local_cogs.djgoowelcome.audio_bridge.asyncio.sleep", no_wait)

    assert await bridge._wait_for_existing_player_music(42) is True


@pytest.mark.asyncio
async def test_restore_starts_current_before_appending_saved_queue() -> None:
    from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

    bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
    calls: list[str] = []
    audio = SimpleNamespace(command_play=object())
    bridge._play_query_when_ready = lambda *_args: _async_result(True)

    async def invoke(_command, _ctx, *, query: str) -> None:
        calls.append(query)

    bridge._invoke_silently = invoke

    result = await bridge._restore_playback_queries(
        audio,
        object(),
        ["current", "next", "later"],
    )

    assert result is True
    assert calls == ["next", "later"]


@pytest.mark.asyncio
async def test_playlist_enqueue_always_skips_duplicates(
    monkeypatch,
) -> None:
    from local_cogs.djgoowelcome import audio_bridge as module

    bridge = module.DjGooAudioBridge.__new__(module.DjGooAudioBridge)
    bridge.playlists = SimpleNamespace(
        get_tracks=lambda _name: [
            {"title": "Already Playing", "uri": "https://youtu.be/AAAAAAAAAAA"},
            {"title": "New Song", "uri": "https://youtu.be/BBBBBBBBBBB"},
        ]
    )
    player = SimpleNamespace(
        current=SimpleNamespace(
            title="Already Playing",
            uri="https://www.youtube.com/watch?v=AAAAAAAAAAA",
            info={},
        ),
        queue=[],
    )
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)
    queued: list[str] = []
    notices: list[str] = []

    async def invoke(_command, _ctx, *, query: str) -> None:
        queued.append(query)
        player.queue.append(SimpleNamespace(title="Queued", uri=query, info={}))

    async def notice(message: str) -> None:
        notices.append(message)

    bridge._invoke = invoke
    bridge._notice = notice
    audio = SimpleNamespace(command_play=object())
    ctx = SimpleNamespace(guild=SimpleNamespace(id=42))

    first = await bridge._play_playlist(audio, ctx, "KnockOut", shuffle=False)
    second = await bridge._play_playlist(audio, ctx, "KnockOut", shuffle=False)

    assert queued == [
        "https://youtu.be/BBBBBBBBBBB",
    ]
    assert "Skipped 1" in first
    assert "already playing or queued" in second
    assert notices == [first, second]


def test_mini_player_track_duplicate_checks_current_and_queue(monkeypatch) -> None:
    from local_cogs.djgoowelcome import request_semantics_bridge as module

    bridge = module.RequestSemanticsDjGooAudioBridge.__new__(
        module.RequestSemanticsDjGooAudioBridge
    )
    bridge._ytmusic = None
    player = SimpleNamespace(
        current=SimpleNamespace(
            title="Never Gonna Give You Up",
            uri="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            info={},
        ),
        queue=[
            SimpleNamespace(
                title="Sandstorm",
                uri="https://youtu.be/y6120QOlsfU",
                info={},
            )
        ],
    )
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)

    assert bridge._mini_player_has_track(
        42,
        "https://youtu.be/dQw4w9WgXcQ",
    )
    assert bridge._mini_player_has_track(
        42,
        "https://www.youtube.com/watch?v=y6120QOlsfU",
    )
    assert not bridge._mini_player_has_track(
        42,
        "https://www.youtube.com/watch?v=BBBBBBBBBBB",
    )


async def _async_result(value):
    return value


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
async def test_queue_remove_uses_row_id_when_tracks_compare_equal(monkeypatch) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module

    class EqualTrack:
        def __init__(self, title: str, uri: str) -> None:
            self.title = title
            self.uri = uri

        def __eq__(self, other: object) -> bool:
            return isinstance(other, EqualTrack) and self.uri == other.uri

    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    bridge.bot = SimpleNamespace(get_cog=lambda _name: object())
    bridge._context = lambda: SimpleNamespace(guild=SimpleNamespace(id=42))
    bridge._queue_item_ids = {}
    bridge._queue_undo = {}
    bridge.request_ledger = SimpleNamespace(
        entries=lambda _guild_id: [],
        consume=lambda _guild_id, _track_key: None,
    )
    bridge._track_key = lambda track: track.uri
    bridge._persist_player_state = lambda *_args, **_kwargs: None
    first = EqualTrack("First copy", "track:same")
    second = EqualTrack("Second copy", "track:same")
    player = SimpleNamespace(queue=[first, second], current=None)
    monkeypatch.setattr(module.lavalink, "get_player", lambda _guild_id: player)
    second_id = bridge._stable_track_id(second)

    result = await bridge._handle_mini_intent(
        {
            "intent": "mini_queue_remove_many",
            "payload": {"track_ids": [second_id]},
        }
    )

    assert result["status"] == "completed"
    assert player.queue == [first]


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


@pytest.mark.asyncio
async def test_playlist_management_intents_are_fully_wired(tmp_path: Path) -> None:
    from local_cogs.djgoowelcome import experience_audio_bridge as module

    bridge = module.ExperienceDjGooAudioBridge.__new__(
        module.ExperienceDjGooAudioBridge
    )
    bridge.playlists = DjGooPlaylists(tmp_path / "playlists.json")

    await bridge._handle_mini_intent(
        {"intent": "mini_playlist_create", "playlist": "Game Night"}
    )
    added = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_add_search",
            "playlist": "Game Night",
            "payload": {
                "tracks": [
                    {"title": "One", "artist": "Artist", "uri": "track:one"},
                    {"title": "Two", "artist": "Artist", "uri": "track:two"},
                ]
            },
        }
    )
    tracks = bridge.playlists.get_tracks("Game Night")
    renamed = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_rename",
            "playlist": "Game Night",
            "payload": {"new_name": "Ranked"},
        }
    )
    reordered = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_reorder",
            "playlist": "Ranked",
            "payload": {"track_ids": [tracks[1]["id"], tracks[0]["id"]]},
        }
    )
    removed = await bridge._handle_mini_intent(
        {
            "intent": "mini_playlist_remove_tracks",
            "playlist": "Ranked",
            "payload": {"track_ids": [tracks[0]["id"]]},
        }
    )
    deleted = await bridge._handle_mini_intent(
        {"intent": "mini_playlist_delete", "playlist": "Ranked"}
    )

    assert added["added"] == 2
    assert renamed["playlist"] == "ranked"
    assert reordered["status"] == "completed"
    assert removed["removed"] == 1
    assert deleted["playlists"] == []
