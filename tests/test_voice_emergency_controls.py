import unittest

from voice.command_parser import parse_emergency_control


class VoiceEmergencyControlsTests(unittest.TestCase):
    def test_accepts_short_playback_controls(self):
        examples = {
            "skip": "skip",
            "skip it": "skip",
            "next song": "skip",
            "stop": "stop",
            "pause music": "pause",
            "resume": "resume",
            "queue": "queue",
            "now playing": "now",
        }

        for transcript, intent in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(parse_emergency_control(transcript).intent, intent)

    def test_rejects_game_chatter_and_song_searches(self):
        for transcript in (
            "it skips like five frames",
            "stop lagging yourself",
            "play sandstorm",
            "skip over to the ball",
            "next time I got it",
        ):
            with self.subTest(transcript=transcript):
                self.assertEqual(parse_emergency_control(transcript).intent, "ignore")


if __name__ == "__main__":
    unittest.main()
