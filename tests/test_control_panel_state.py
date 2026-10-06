import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_panel.state import (
    build_health,
    build_state_snapshot,
    read_recent_log_lines,
)


class ControlPanelStateTests(unittest.TestCase):
    def test_build_state_snapshot_reads_playlists_stations_and_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "logs").mkdir()
            (root / "data" / "djgoo-playlists.json").write_text(
                json.dumps(
                    {
                        "playlists": {
                            "chill": {
                                "tracks": [
                                    {"title": "Song", "uri": "u:song"}
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "djgoo-stations.json").write_text(
                json.dumps(
                    {
                        "active": {"123": "80s"},
                        "stations": {
                            "80s": {
                                "id": "80s",
                                "name": "80S radio",
                                "seed": "80s",
                                "liked": [
                                    {"title": "Like", "uri": "u:like"}
                                ],
                                "more_like": [],
                                "less_like": [],
                                "banned": [],
                                "skipped": [],
                                "recent": [],
                                "played": [],
                                "last_track": {
                                    "title": "Last",
                                    "uri": "u:last",
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "logs" / "voice-listener.log").write_text(
                "voice ready\n",
                encoding="utf-8",
            )

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["playlists"][0]["name"], "chill")
        self.assertEqual(snapshot["stations"][0]["name"], "80S radio")
        self.assertEqual(snapshot["active_station"]["name"], "80S radio")
        self.assertIn("redbot", snapshot["health"])
        self.assertIn("health_summary", snapshot)
        self.assertEqual(snapshot["logs"]["voice"][-1], "voice ready")

    def test_supervisor_ready_state_is_authoritative_for_portable_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "data" / "djgoo-supervisor-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "desired_running": True,
                        "last_error": "",
                        "components": {
                            "redbot": {
                                "pid": 101,
                                "running": True,
                                "ready": True,
                            },
                            "lavalink": {
                                "pid": 102,
                                "running": True,
                                "ready": True,
                            },
                            "voice": {
                                "pid": 103,
                                "running": True,
                                "ready": True,
                            },
                            "web": {
                                "pid": 104,
                                "running": True,
                                "ready": True,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "control_panel.state.subprocess.check_output",
                side_effect=AssertionError("process guessing must not run"),
            ):
                health = build_health(root)
                snapshot = build_state_snapshot(root)

        for component in ("redbot", "lavalink", "voice", "web"):
            self.assertEqual(health[component]["status"], "online")
            self.assertEqual(health[component]["source"], "supervisor")
        self.assertTrue(snapshot["health_summary"]["ok"])
        self.assertEqual(snapshot["health_summary"]["failed_components"], [])

    def test_running_component_is_reported_as_starting_not_failed_process_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "data" / "djgoo-supervisor-state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps(
                    {
                        "desired_running": True,
                        "last_error": "voice did not become ready",
                        "components": {
                            "voice": {
                                "pid": 203,
                                "running": True,
                                "ready": False,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            status = build_health(root)["voice"]

        self.assertEqual(status["status"], "starting")
        self.assertEqual(status["pid"], "203")
        self.assertIn("voice did not become ready", status["detail"])

    def test_redbot_process_fallback_uses_portable_python_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch(
                "control_panel.state.subprocess.check_output",
                return_value="4321\n",
            ) as process_query:
                health = build_health(root)

        redbot_command = process_query.call_args_list[0].args[0][-1]
        self.assertIn("python.exe", redbot_command)
        self.assertIn("start_redbot_selector.py", redbot_command)
        self.assertEqual(health["redbot"]["status"], "online")
        self.assertEqual(health["redbot"]["pid"], "4321")

    def test_health_summary_names_failed_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch(
                "control_panel.state.subprocess.check_output",
                return_value="",
            ):
                snapshot = build_state_snapshot(root)

        self.assertFalse(snapshot["health_summary"]["ok"])
        self.assertEqual(
            snapshot["health_summary"]["failed_components"],
            ["redbot", "lavalink", "voice", "web"],
        )
        self.assertIn("redbot", snapshot["health_summary"]["message"])

    def test_read_recent_log_lines_returns_tail_without_error_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.log"

            self.assertEqual(read_recent_log_lines(missing, limit=5), [])

    def test_read_recent_log_lines_limits_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.log"
            path.write_text("a\nb\nc\n", encoding="utf-8")

            self.assertEqual(read_recent_log_lines(path, limit=2), ["b", "c"])

    def test_history_uses_cached_local_track_artist_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            cache = root / "cache" / "localtracks"
            cache.mkdir(parents=True)
            (root / "data" / "djgoo-mini-history.json").write_text(
                json.dumps({"entries": [{"id": "one", "title": "Song", "artist": "Unknown artist", "uri": str(cache / "one.webm")}]}),
                encoding="utf-8",
            )
            (cache / "metadata.json").write_text(
                json.dumps({"one.webm": {"title": "Song", "artist": "Correct Artist", "source_uri": "https://example.test/song"}}),
                encoding="utf-8",
            )

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["history"][0]["artist"], "Correct Artist")
        self.assertEqual(snapshot["history"][0]["uri"], "https://example.test/song")
        self.assertNotIn("AppData", json.dumps(snapshot["history"][0]))

    def test_history_uses_source_url_artist_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            cache = root / "cache" / "localtracks"
            cache.mkdir(parents=True)
            source = "https://www.youtube.com/watch?v=example"
            (root / "data" / "djgoo-mini-history.json").write_text(
                json.dumps({"entries": [{"id": "one", "title": "Song", "artist": "Unknown artist", "uri": source}]}),
                encoding="utf-8",
            )
            (cache / "metadata.json").write_text(
                json.dumps({"one.webm": {"title": "Song", "artist": "Correct Artist", "source_uri": source}}),
                encoding="utf-8",
            )

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["history"][0]["artist"], "Correct Artist")
        self.assertEqual(snapshot["history"][0]["uri"], source)

    def test_history_never_exposes_unmapped_local_cache_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            cache = root / "cache" / "localtracks"
            cache.mkdir(parents=True)
            (root / "data" / "djgoo-mini-history.json").write_text(
                json.dumps({"entries": [{"id": "one", "title": "Song", "uri": str(cache / "one.webm")}]}),
                encoding="utf-8",
            )
            (cache / "metadata.json").write_text(json.dumps({"one.webm": {"title": "Song"}}), encoding="utf-8")

            snapshot = build_state_snapshot(root)

        self.assertNotIn("uri", snapshot["history"][0])

    def test_now_playing_uses_cached_local_track_artist_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            cache = root / "cache" / "localtracks"
            cache.mkdir(parents=True)
            (root / "data" / "djgoo-now-playing.json").write_text(
                json.dumps({"current": {"title": "Song", "artist": "Unknown artist", "uri": str(cache / "one.webm")}}),
                encoding="utf-8",
            )
            (cache / "metadata.json").write_text(
                json.dumps({"one.webm": {"title": "Song", "artist": "Correct Artist", "artwork_url": "https://img.invalid/one.jpg"}}),
                encoding="utf-8",
            )

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["playback"]["artist"], "Correct Artist")
        self.assertEqual(snapshot["playback"]["artwork_url"], "https://img.invalid/one.jpg")


if __name__ == "__main__":
    unittest.main()
