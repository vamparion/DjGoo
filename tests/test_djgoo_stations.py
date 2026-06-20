import json
import tempfile
import unittest
from pathlib import Path

from voice.djgoo_stations import DjGooStations, normalize_station_seed, track_key


class DjGooStationsTests(unittest.TestCase):
    def test_radio_seed_creates_stable_station_name(self):
        self.assertEqual(normalize_station_seed("  Sandstorm  "), "sandstorm")
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.get_or_create("Sandstorm")
            resumed = stations.get_or_create("sandstorm")

            self.assertEqual(station["name"], "Sandstorm radio")
            self.assertEqual(resumed["id"], station["id"])
            self.assertEqual(resumed["seed"], "Sandstorm")

    def test_lowercase_seed_creates_title_cased_station_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.get_or_create("sandstorm")

            self.assertEqual(station["name"], "Sandstorm radio")

    def test_station_memories_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.add_feedback("Sandstorm", "liked", {"title": "A", "uri": "u:a"})
            stations.add_feedback("Chill", "liked", {"title": "B", "uri": "u:b"})

            self.assertEqual(stations.get_station("Sandstorm")["liked"][0]["title"], "A")
            self.assertEqual(stations.get_station("Chill")["liked"][0]["title"], "B")

    def test_banned_and_recent_tracks_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.get_or_create("Sandstorm")
            stations.add_feedback("Sandstorm", "banned", {"title": "Bad", "uri": "u:bad"})
            stations.mark_played("Sandstorm", {"title": "Recent", "uri": "u:recent"})

            candidates = [
                {"title": "Bad", "uri": "u:bad"},
                {"title": "Recent", "uri": "u:recent"},
                {"title": "Fresh", "uri": "u:fresh"},
            ]

            picked = stations.pick_candidate("Sandstorm", candidates, rng_seed=1)

            self.assertEqual(picked["title"], "Fresh")

    def test_active_station_is_per_guild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stations.json"
            stations = DjGooStations(path)
            guild_one_station = stations.set_active(10, "Sandstorm")
            guild_two_station = stations.set_active(20, "Chill")

            self.assertEqual(stations.get_active(10)["id"], guild_one_station["id"])
            self.assertEqual(stations.get_active(20)["id"], guild_two_station["id"])
            self.assertNotEqual(stations.get_active(10)["id"], stations.get_active(20)["id"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["active"]["10"], "sandstorm")

    def test_station_contains_planned_storage_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.get_or_create("Sandstorm")

            self.assertEqual(
                set(station),
                {
                    "id",
                    "name",
                    "seed",
                    "created_at",
                    "updated_at",
                    "played",
                    "recent",
                    "liked",
                    "banned",
                    "more_like",
                    "less_like",
                    "skipped",
                    "last_track",
                },
            )

    def test_mark_played_updates_played_recent_and_last_track(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.mark_played("Sandstorm", {"title": "Recent", "uri": "u:recent"})

            self.assertEqual(station["played"][0]["title"], "Recent")
            self.assertEqual(station["recent"][0]["title"], "Recent")
            self.assertEqual(station["last_track"]["title"], "Recent")

    def test_feedback_dedupes_tracks_by_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.add_feedback("Sandstorm", "liked", {"title": "Song", "uri": "u:song"})
            station = stations.add_feedback("Sandstorm", "liked", {"title": "Song again", "uri": "u:song"})

            self.assertEqual(len(station["liked"]), 1)

    def test_track_key_prefers_uri_and_falls_back_to_title(self):
        self.assertEqual(track_key({"title": "Song", "uri": "https://x"}), "uri:https://x")
        self.assertEqual(track_key({"title": "Song", "uri": ""}), "title:song")
        self.assertEqual(track_key({"title": "Song  Title", "uri": ""}), "title:song title")


if __name__ == "__main__":
    unittest.main()
