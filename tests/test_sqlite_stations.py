from __future__ import annotations

import json
from pathlib import Path

from voice.sqlite_stations import SqliteDjGooStations


def test_migrates_legacy_json_and_preserves_active_station(tmp_path: Path) -> None:
    legacy = tmp_path / "stations.json"
    legacy.write_text(
        json.dumps(
            {
                "active": {"123": "rock"},
                "stations": {
                    "rock": {
                        "id": "rock",
                        "name": "Rock radio",
                        "seed": "Rock",
                        "played": [],
                        "recent": [],
                        "liked": [],
                        "banned": [],
                        "more_like": [],
                        "less_like": [],
                        "skipped": [],
                        "last_track": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = SqliteDjGooStations(tmp_path / "stations.sqlite3", legacy_json_path=legacy)
    assert store.get_active(123)["seed"] == "Rock"


def test_feedback_writes_are_deduplicated_and_removable(tmp_path: Path) -> None:
    store = SqliteDjGooStations(tmp_path / "stations.sqlite3")
    store.set_active(123, "Rock")
    track = {"title": "Artist - Song", "artist": "Artist", "uri": "media:song"}
    store.add_feedback("Rock", "banned", track)
    store.add_feedback("Rock", "banned", track)
    station = store.get_active(123)
    assert len(station["banned"]) == 1
    store.remove_feedback("Rock", "banned", track)
    assert store.get_active(123)["banned"] == []


def test_play_history_is_bounded(tmp_path: Path) -> None:
    store = SqliteDjGooStations(tmp_path / "stations.sqlite3")
    for index in range(75):
        store.mark_played("Rock", {"title": f"Song {index}", "uri": f"media:{index}"})
    station = store.get_station("Rock")
    assert len(station["recent"]) == 50
    assert station["recent"][-1]["title"] == "Song 74"


def test_seed_track_does_not_count_as_played(tmp_path: Path) -> None:
    store = SqliteDjGooStations(tmp_path / "stations.sqlite3")
    station = store.set_seed_track("Rock", {"title": "Seed", "uri": "media:seed"})
    assert station["seed_track"]["uri"] == "media:seed"
    assert station["played"] == []
    assert station["recent"] == []


def test_station_tuning_feedback_undo_snapshot_clone_and_merge(tmp_path: Path) -> None:
    store = SqliteDjGooStations(tmp_path / "stations.sqlite3")
    store.add_feedback("Rock", "liked", {"title": "One", "artist": "Band", "uri": "track:one"})
    tuned = store.update_settings("Rock", {"familiar_percent": 70, "artist_spacing": 6, "seed_type": "genre"})
    snapshot = store.create_snapshot("Rock", "Good mix")
    store.update_settings("Rock", {"familiar_percent": 10})
    restored = store.restore_snapshot("Rock", snapshot["id"])
    clone = store.clone("Rock", "Rock Copy")
    store.add_feedback("90s", "banned", {"title": "Two", "uri": "track:two"})
    merged = store.merge(["Rock", "90s"], "Rock 90s")
    assert tuned["artist_spacing"] == 6
    assert restored["familiar_percent"] == 70
    assert clone["played"] == [] and len(clone["liked"]) == 1
    assert len(merged["liked"]) == 1 and len(merged["banned"]) == 1
    assert store.undo_feedback("Rock", "liked")["liked"] == []
