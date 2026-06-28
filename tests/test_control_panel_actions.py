import json
import tempfile
import unittest
from pathlib import Path

from control_panel.actions import enqueue_panel_command, queue_path_for_project, resolve_panel_action


class ControlPanelActionTests(unittest.TestCase):
    def test_resolve_panel_action_maps_play_next_to_play_command(self):
        item = resolve_panel_action({"action": "play_next", "query": "Sandstorm"})

        self.assertEqual(item["intent"], "play")
        self.assertEqual(item["query"], "Sandstorm")
        self.assertEqual(item["source"], "panel")

    def test_resolve_panel_action_maps_radio(self):
        item = resolve_panel_action({"action": "start_radio", "query": "80s"})

        self.assertEqual(item["intent"], "start_radio")
        self.assertEqual(item["query"], "80s")

    def test_resolve_panel_action_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            resolve_panel_action({"action": "explode"})

    def test_enqueue_panel_command_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = enqueue_panel_command(root, {"action": "skip"})
            queue_path = queue_path_for_project(root)
            lines = queue_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(item["intent"], "skip")
        self.assertEqual(json.loads(lines[0])["intent"], "skip")


if __name__ == "__main__":
    unittest.main()
