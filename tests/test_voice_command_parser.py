import unittest

from voice.command_parser import (
    PendingChoice,
    parse_command,
    parse_followup,
)


class VoiceCommandParserTests(unittest.TestCase):
    def test_ignores_speech_without_wake_phrase(self):
        parsed = parse_command("play sandstorm")

        self.assertEqual(parsed.intent, "ignore")
        self.assertEqual(parsed.confidence, 0.0)

    def test_push_to_talk_mode_does_not_require_wake_phrase(self):
        examples = {
            "play Sandstorm": ("play", "Sandstorm"),
            "PLAY SANDSTORM": ("play", "SANDSTORM"),
            "skip": ("skip", ""),
            "SKIP": ("skip", ""),
            "radio Sandstorm": ("start_radio", "Sandstorm"),
            "play album Discovery": ("play_album", "Discovery"),
        }

        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                parsed = parse_command(transcript, require_wake=False)

                self.assertEqual(parsed.intent, expected[0])
                self.assertEqual(parsed.query, expected[1])

    def test_parses_play_command_after_djgoo_wake_phrase(self):
        for wake_phrase in ["DjGoo", "DJ Goo", "DJ Koo", "DJ Goon", "DJ", "Dj", "DeeJay", "dee jay", "D J"]:
            with self.subTest(wake_phrase=wake_phrase):
                parsed = parse_command(f"{wake_phrase} play Sandstorm")

                self.assertEqual(parsed.intent, "play")
                self.assertEqual(parsed.query, "Sandstorm")
                self.assertGreaterEqual(parsed.confidence, 0.9)

    def test_parses_wake_phrase_after_short_filler(self):
        examples = {
            "Okay, so DjGoo play Sandstorm": ("play", "Sandstorm"),
            "alright Dj Goo skip": ("skip", ""),
            "can you DeeJay stop": ("stop", ""),
        }

        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                parsed = parse_command(transcript)

                self.assertEqual(parsed.intent, expected[0])
                self.assertEqual(parsed.query, expected[1])

    def test_ignores_wake_phrase_with_only_punctuation(self):
        for transcript in ["DJ Goo.", "DJ Koo.", "DJ Goon.", "DjGoo,", "DJ!", "DeeJay ..."]:
            with self.subTest(transcript=transcript):
                parsed = parse_command(transcript)

                self.assertEqual(parsed.intent, "ignore")
                self.assertEqual(parsed.confidence, 0.0)

    def test_parses_common_whisper_mishearing_of_play_command(self):
        parsed = parse_command("DJ Goon, ice Sandstorm")

        self.assertEqual(parsed.intent, "play")
        self.assertEqual(parsed.query, "Sandstorm")

    def test_song_titles_with_stop_are_not_control_commands(self):
        examples = {
            "play dont stop the music": ("play", "dont stop the music"),
            "PLAY DON'T STOP THE MUSIC": ("play", "DON'T STOP THE MUSIC"),
            "DjGoo play dont stop the music": ("play", "dont stop the music"),
            "DjGoo don't stop the music": ("unknown", ""),
        }

        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                parsed = parse_command(transcript, require_wake=transcript.lower().startswith("dj"))

                self.assertEqual(parsed.intent, expected[0])
                if expected[1]:
                    self.assertEqual(parsed.query, expected[1])

    def test_does_not_wake_on_casual_mentions_of_dj(self):
        parsed = parse_command("that DJ was great play sandstorm")

        self.assertEqual(parsed.intent, "ignore")

        parsed = parse_command("the DJ Goo joke was funny play sandstorm")

        self.assertEqual(parsed.intent, "ignore")

    def test_parses_fast_music_controls(self):
        examples = {
            "DJ Goo skip this": "skip",
            "djgoo pause": "pause",
            "DjGoo resume music": "resume",
            "DjGoo stop": "stop",
            "DjGoo what is playing": "now",
            "DjGoo clear queue": "clear_queue",
            "DjGoo replay this": "replay",
        }

        for transcript, intent in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(parse_command(transcript).intent, intent)

    def test_parses_volume_and_relative_volume(self):
        self.assertEqual(parse_command("DjGoo volume 40").intent, "volume")
        self.assertEqual(parse_command("DjGoo volume 40").value, 40)
        self.assertEqual(parse_command("DjGoo louder").intent, "volume_up")
        self.assertEqual(parse_command("DjGoo quieter").intent, "volume_down")

    def test_parses_playlist_save_and_play(self):
        save = parse_command("DjGoo save the last song to white girl music")
        play = parse_command("DjGoo shuffle 80s")

        self.assertEqual(save.intent, "save_last_to_playlist")
        self.assertEqual(save.playlist, "white girl music")
        self.assertEqual(play.intent, "shuffle_playlist")
        self.assertEqual(play.playlist, "80s")

    def test_parses_album_play(self):
        parsed = parse_command("DjGoo play album Discovery")

        self.assertEqual(parsed.intent, "play_album")
        self.assertEqual(parsed.query, "Discovery")

    def test_parses_radio_station_commands(self):
        radio = parse_command("DjGoo radio Sandstorm")
        self.assertEqual(radio.intent, "start_radio")
        self.assertEqual(radio.query, "Sandstorm")

        examples = {
            "DjGoo like this": "station_like_current",
            "DjGoo more like this": "station_more_like_current",
            "DjGoo less like this": "station_less_like_current",
            "DjGoo don't play this again": "station_ban_current",
            "DjGoo do not play this again": "station_ban_current",
            "DjGoo station status": "station_status",
            "DjGoo radio status": "station_status",
            "DjGoo stop radio": "stop_radio",
            "DjGoo radio off": "stop_radio",
            "DjGoo end radio": "stop_radio",
        }
        for transcript, intent in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(parse_command(transcript).intent, intent)

    def test_negative_like_phrases_parse_as_negative_station_feedback(self):
        for transcript in (
            "DjGoo I don't like this",
            "DjGoo don't like this",
            "DjGoo I do not like this",
            "DjGoo do not like this",
        ):
            with self.subTest(transcript=transcript):
                parsed = parse_command(transcript)
                self.assertEqual(parsed.intent, "station_less_like_current")
                self.assertNotEqual(parsed.intent, "station_like_current")

    def test_parses_pending_choice_naturally(self):
        pending = PendingChoice(kind="search", options=["a", "b", "c", "d"], created_at=100.0)

        for transcript in ["number 2", "pick two", "second one", "play option 2", "that second one"]:
            with self.subTest(transcript=transcript):
                followup = parse_followup(transcript, pending, now=110.0)
                self.assertEqual(followup.action, "choose")
                self.assertEqual(followup.index, 1)

    def test_parses_neither_cancel_and_expiration(self):
        pending = PendingChoice(kind="search", options=["a", "b"], created_at=100.0)

        self.assertEqual(parse_followup("neither", pending, now=110.0).action, "neither")
        self.assertEqual(parse_followup("never mind", pending, now=110.0).action, "cancel")
        self.assertEqual(parse_followup("number 1", pending, now=116.0).action, "expired")


if __name__ == "__main__":
    unittest.main()
