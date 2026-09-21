from __future__ import annotations

import pytest

from voice.playback_lifecycle import PlaybackLifecycleStore
from voice.queue_transactions import QueueTransactionStore


def test_lifecycle_records_complete_verified_path(tmp_path) -> None:
    store = PlaybackLifecycleStore(tmp_path / "lifecycle.json")
    operation = store.begin(42, intent="play", source="voice", query="Sandstorm")
    store.transition(42, operation, "queued", track_key="sandstorm")
    store.transition(42, operation, "loading")
    store.transition(42, operation, "playing", track={"title": "Sandstorm"})
    final = store.transition(42, operation, "ended", reason="Track completed")

    assert final["state"] == "ended"
    assert [event["state"] for event in final["events"]] == [
        "searching",
        "queued",
        "loading",
        "playing",
        "ended",
    ]
    assert store.latest(42)["state"] == "ended"


def test_lifecycle_rejects_impossible_transition(tmp_path) -> None:
    store = PlaybackLifecycleStore(tmp_path / "lifecycle.json")
    operation = store.begin(42, intent="play", source="chat")

    with pytest.raises(ValueError, match="searching -> playing"):
        store.transition(42, operation, "playing")


def test_failures_remain_available_for_diagnostics(tmp_path) -> None:
    store = PlaybackLifecycleStore(tmp_path / "lifecycle.json")
    operation = store.begin(42, intent="skip", source="mini_player")
    store.transition(42, operation, "failed", reason="Player did not advance")

    assert store.failures(42)[0]["reason"] == "Player did not advance"


def test_queue_transaction_is_durable_and_keeps_stable_metadata(tmp_path) -> None:
    path = tmp_path / "transactions.json"
    first = QueueTransactionStore(path)
    transaction_id = first.record(
        42,
        action="reorder",
        before=[{"id": "a", "lane": "request"}, {"id": "b", "lane": "radio"}],
        after=[{"id": "b", "lane": "radio"}, {"id": "a", "lane": "request"}],
        source="mini_player",
        reason="Drag reorder",
        operation_id="operation-1",
    )

    latest = QueueTransactionStore(path).latest(42)
    assert latest["transaction_id"] == transaction_id
    assert latest["before"][0]["id"] == "a"
    assert latest["after"][0]["id"] == "b"
