import tempfile
import unittest
from pathlib import Path

from voice.command_parser import FollowupResult, ParsedCommand
from voice.command_queue import (
    append_queue_item,
    command_to_queue_item,
    drain_queue,
    followup_to_queue_item,
)


class VoiceCommandQueueTests(unittest.TestCase):
    def test_command_to_queue_item_preserves_command_details(self):
        command = ParsedCommand(
            intent="play",
            query="Sandstorm",
            playlist="",
            value=None,
            confidence=0.95,
            raw="DjGoo play Sandstorm",
        )

        item = command_to_queue_item(command, transcript="DjGoo play Sandstorm", created_at=123.5)

        self.assertEqual(item["type"], "command")
        self.assertEqual(item["source"], "voice")
        self.assertEqual(item["created_at"], 123.5)
        self.assertEqual(item["intent"], "play")
        self.assertEqual(item["query"], "Sandstorm")
        self.assertEqual(item["playlist"], "")
        self.assertIsNone(item["value"])
        self.assertEqual(item["confidence"], 0.95)
        self.assertEqual(item["raw"], "DjGoo play Sandstorm")

    def test_followup_to_queue_item_preserves_choice_details(self):
        followup = FollowupResult(action="choose", index=1, raw="number two")

        item = followup_to_queue_item(followup, transcript="number two", created_at=456.0)

        self.assertEqual(item["type"], "followup")
        self.assertEqual(item["source"], "voice")
        self.assertEqual(item["created_at"], 456.0)
        self.assertEqual(item["action"], "choose")
        self.assertEqual(item["index"], 1)
        self.assertEqual(item["raw"], "number two")

    def test_append_and_drain_queue_round_trips_items_and_removes_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "voice-command-queue.jsonl"
            first = {"type": "command", "intent": "skip"}
            second = {"type": "followup", "action": "cancel"}

            append_queue_item(queue_path, first)
            append_queue_item(queue_path, second)

            self.assertEqual(drain_queue(queue_path), [first, second])
            self.assertFalse(queue_path.exists())
            self.assertEqual(drain_queue(queue_path), [])

    def test_drain_queue_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "voice-command-queue.jsonl"
            queue_path.write_text('{"type":"command","intent":"pause"}\nnot json\n', encoding="utf-8")

            self.assertEqual(drain_queue(queue_path), [{"type": "command", "intent": "pause"}])

    def test_drain_queue_accepts_utf8_bom_from_windows_powershell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "voice-command-queue.jsonl"
            queue_path.write_text('\ufeff{"type":"command","intent":"now"}\n', encoding="utf-8")

            self.assertEqual(drain_queue(queue_path), [{"type": "command", "intent": "now"}])


if __name__ == "__main__":
    unittest.main()
