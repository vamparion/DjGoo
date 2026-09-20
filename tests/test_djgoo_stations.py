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

    def test_normalize_station_seed_does_not_truncate_long_seeds(self):
        seed = "A" * 65

        self.assertEqual(normalize_station_seed(seed), "a" * 65)

    def test_lowercase_seed_creates_title_cased_station_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.get_or_create("sandstorm")

            self.assertEqual(station["name"], "Sandstorm radio")

    def test_station_preserves_cleaned_original_seed_casing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")

            self.assertEqual(stations.get_or_create("  deadmau5  ")["seed"], "deadmau5")
            self.assertEqual(stations.get_or_create(" AC/DC ")["seed"], "AC/DC")

    def test_get_station_missing_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stations.json"
            stations = DjGooStations(path)

            self.assertIsNone(stations.get_station("missing"))
            self.assertFalse(path.exists())

    def test_malformed_json_reads_as_empty_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stations.json"
            path.write_text("{not-json", encoding="utf-8")
            stations = DjGooStations(path)

            self.assertIsNone(stations.get_station("missing"))

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
            self.assertEqual(stations.active_guild_ids(), [10, 20])

    def test_clear_active_station_only_removes_requested_guild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stations.json"
            stations = DjGooStations(path)
            stations.set_active(10, "Sandstorm")
            other_station = stations.set_active(20, "Chill")

            stations.clear_active(10)

            self.assertIsNone(stations.get_active(10))
            self.assertEqual(stations.get_active(20)["id"], other_station["id"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["active"], {"20": "chill"})

    def test_clear_all_active_stations_keeps_station_memories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stations.json"
            stations = DjGooStations(path)
            stations.set_active(10, "Sandstorm")
            stations.set_active(20, "Chill")
            stations.add_feedback("Sandstorm", "liked", {"title": "A", "uri": "u:a"})

            stations.clear_all_active()

            self.assertIsNone(stations.get_active(10))
            self.assertIsNone(stations.get_active(20))
            self.assertEqual(stations.get_station("Sandstorm")["liked"][0]["title"], "A")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["active"], {})

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

    def test_seed_track_does_not_count_as_played(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.set_seed_track("Sandstorm", {"title": "Darude - Sandstorm", "uri": "u:seed"})

            self.assertEqual(station["seed_track"]["uri"], "u:seed")
            self.assertEqual(station["played"], [])
            self.assertEqual(station["recent"], [])

    def test_feedback_dedupes_tracks_by_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.add_feedback("Sandstorm", "liked", {"title": "Song", "uri": "u:song"})
            station = stations.add_feedback("Sandstorm", "liked", {"title": "Song again", "uri": "u:song"})

            self.assertEqual(len(station["liked"]), 1)

    def test_feedback_rejects_unknown_bucket_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")

            with self.assertRaises(ValueError):
                stations.add_feedback("Sandstorm", "favorite", {"title": "Song", "uri": "u:song"})

    def test_track_key_prefers_uri_and_falls_back_to_title(self):
        self.assertEqual(track_key({"title": "Song", "uri": "https://x"}), "uri:https://x")
        self.assertEqual(track_key({"title": "Song", "uri": ""}), "title:song")
        self.assertEqual(track_key({"title": "Song  Title", "uri": ""}), "title:song title")


if __name__ == "__main__":
    unittest.main()
