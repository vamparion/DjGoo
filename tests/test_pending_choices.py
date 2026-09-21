from __future__ import annotations

from voice.pending_choices import PendingChoiceStore


def test_pending_choice_round_trip_and_consumption(tmp_path) -> None:
    store = PendingChoiceStore(tmp_path / "choice.json")
    store.set(
        query="Shadows Lindsey Stirling",
        options=[
            {"title": "Shadows", "artist": "Lindsey Stirling", "uri": "one"},
            {"title": "Shadow", "artist": "Other", "uri": "two"},
        ],
        guild_id=42,
    )

    assert store.get()["guild_id"] == 42
    assert store.choose(0)["uri"] == "one"
    assert store.get() is None
