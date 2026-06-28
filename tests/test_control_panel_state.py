import json
import tempfile
import unittest
from pathlib import Path

from control_panel.state import build_state_snapshot, read_recent_log_lines


class ControlPanelStateTests(unittest.TestCase):
    def test_build_state_snapshot_reads_playlists_stations_and_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "logs").mkdir()
            (root / "data" / "djgoo-playlists.json").write_text(
                json.dumps({"playlists": {"chill": {"tracks": [{"title": "Song", "uri": "u:song"}]}}}),
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
                                "liked": [{"title": "Like", "uri": "u:like"}],
                                "more_like": [],
                                "less_like": [],
                                "banned": [],
                                "skipped": [],
                                "recent": [],
                                "played": [],
                                "last_track": {"title": "Last", "uri": "u:last"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "logs" / "voice-listener.log").write_text("voice ready\n", encoding="utf-8")

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["playlists"][0]["name"], "chill")
        self.assertEqual(snapshot["stations"][0]["name"], "80S radio")
        self.assertEqual(snapshot["active_station"]["name"], "80S radio")
        self.assertIn("redbot", snapshot["health"])
        self.assertEqual(snapshot["logs"]["voice"][-1], "voice ready")

    def test_read_recent_log_lines_returns_tail_without_error_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.log"

            self.assertEqual(read_recent_log_lines(missing, limit=5), [])

    def test_read_recent_log_lines_limits_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.log"
            path.write_text("a\nb\nc\n", encoding="utf-8")

            self.assertEqual(read_recent_log_lines(path, limit=2), ["b", "c"])


if __name__ == "__main__":
    unittest.main()
