import unittest
from pathlib import Path

from voice.listener_settings import DEFAULT_COMMAND_HOTWORDS, voice_settings


class VoiceListenerSettingsTests(unittest.TestCase):
    def test_voice_settings_default_to_push_to_talk_and_stronger_model(self):
        settings = voice_settings({}, Path("C:/DjGoo"))

        self.assertEqual(settings["model_name"], "small.en")
        self.assertEqual(settings["hotkey"], "F12")
        self.assertTrue(settings["push_to_talk"])
        self.assertGreaterEqual(settings["beam_size"], 5)
        self.assertIn("DjGoo", settings["hotwords"])

    def test_voice_settings_preserve_configured_queue_and_model(self):
        settings = voice_settings(
            {
                "model": "medium.en",
                "queue_path": "C:/DjGoo/custom.jsonl",
                "push_to_talk": False,
                "hotkey": "F10",
                "hotwords": "DjGoo play skip",
                "input_device": "SteelSeries Sonar",
            },
            Path("C:/DjGoo"),
        )

        self.assertEqual(settings["model_name"], "medium.en")
        self.assertEqual(settings["queue_path"], Path("C:/DjGoo/custom.jsonl"))
        self.assertFalse(settings["push_to_talk"])
        self.assertEqual(settings["hotkey"], "F10")
        self.assertEqual(settings["hotwords"], "DjGoo play skip")
        self.assertEqual(settings["input_device"], "SteelSeries Sonar")
        self.assertTrue(settings["emergency_voice_controls"])

    def test_default_hotwords_cover_fast_music_commands(self):
        for word in ("DjGoo", "play", "skip", "pause", "resume", "radio", "Sandstorm"):
            with self.subTest(word=word):
                self.assertIn(word, DEFAULT_COMMAND_HOTWORDS)


if __name__ == "__main__":
    unittest.main()
