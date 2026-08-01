from __future__ import annotations

from pathlib import Path

from voice.deck_store import DeckStore
from voice.now_playing_state import NowPlayingState


def test_deck_store_round_trip_and_clear(tmp_path: Path) -> None:
    store = DeckStore(tmp_path / "decks.json")

    store.set(123, channel_id=456, message_id=789)

    assert store.get(123) == {"channel_id": 456, "message_id": 789}
    store.clear(123)
    assert store.get(123) is None


def test_now_playing_returns_most_recent_guild(tmp_path: Path) -> None:
    state = NowPlayingState(tmp_path / "now.json")
    state.publish(1, {"title": "First", "mode": "RADIO"})
    state.publish(2, {"title": "Second", "mode": "REQUEST"})

    latest = state.latest()

    assert latest is not None
    assert latest["guild_id"] == 2
    assert latest["title"] == "Second"
    state.clear(2)
    assert state.latest()["guild_id"] == 1
