import importlib.util
import tempfile
import unittest
from pathlib import Path


HELPERS_PATH = (
    Path(__file__).resolve().parents[1]
    / "local_cogs"
    / "djgoowelcome"
    / "helpers.py"
)


def load_helpers():
    spec = importlib.util.spec_from_file_location("djgoowelcome_helpers", HELPERS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyUser:
    def __init__(self, *, bot=False):
        self.bot = bot


class DummyState:
    def __init__(self, channel):
        self.channel = channel


class DjGooWelcomeHelperTests(unittest.TestCase):
    def test_should_send_welcome_when_human_joins_voice_channel(self):
        helpers = load_helpers()

        self.assertTrue(
            helpers.should_send_welcome(
                DummyUser(bot=False),
                DummyState(channel=None),
                DummyState(channel=object()),
            )
        )

    def test_should_not_send_welcome_for_bots_or_non_join_events(self):
        helpers = load_helpers()
        channel = object()

        self.assertFalse(
            helpers.should_send_welcome(
                DummyUser(bot=True),
                DummyState(channel=None),
                DummyState(channel=channel),
            )
        )
        self.assertFalse(
            helpers.should_send_welcome(
                DummyUser(bot=False),
                DummyState(channel=channel),
                DummyState(channel=channel),
            )
        )
        self.assertFalse(
            helpers.should_send_welcome(
                DummyUser(bot=False),
                DummyState(channel=channel),
                DummyState(channel=None),
            )
        )

    def test_build_welcome_payload_contains_sensible_djgoo_commands(self):
        helpers = load_helpers()

        payload = helpers.build_welcome_payload("Vera", "Music Room")

        self.assertEqual(payload["username"], "DjGoo")
        self.assertEqual(payload["embeds"][0]["title"], "Welcome to Music Room")
        description = payload["embeds"][0]["description"]
        self.assertIn("DjGoo play <song or URL>", description)
        self.assertIn("DjGoo, skip", description)
        self.assertIn("DjGoo stop", description)
        self.assertIn("!radio <song, artist, or genre>", description)
        self.assertIn("Type these in chat", description)
        self.assertIn("Vera", description)
        self.assertNotIn("listening", description.lower())
        self.assertNotIn("saying", description.lower())

    def test_load_secrets_returns_empty_webhook_for_missing_or_placeholder_file(self):
        helpers = load_helpers()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            self.assertEqual(helpers.load_secrets(temp_path / "missing.json")["webhook_url"], "")

            secrets_path = temp_path / "secrets.json"
            secrets_path.write_text(
                '{"webhook_url": "PASTE_NEW_WEBHOOK_URL_HERE"}',
                encoding="utf-8",
            )

            self.assertEqual(helpers.load_secrets(secrets_path)["webhook_url"], "")

    def test_load_secrets_returns_voice_queue_path(self):
        helpers = load_helpers()
        with tempfile.TemporaryDirectory() as temp_dir:
            secrets_path = Path(temp_dir) / "secrets.json"
            secrets_path.write_text(
                '{"webhook_url": "", "voice": {"queue_path": "C:/DjGoo/queue.jsonl"}}',
                encoding="utf-8",
            )

            secrets = helpers.load_secrets(secrets_path)

        self.assertEqual(secrets["voice"]["queue_path"], "C:/DjGoo/queue.jsonl")

    def test_load_secrets_preserves_voice_gateway_settings(self):
        helpers = load_helpers()
        with tempfile.TemporaryDirectory() as temp_dir:
            secrets_path = Path(temp_dir) / "secrets.json"
            secrets_path.write_text(
                '{"voice_gateway": {"enabled": true, "port": 49178}}',
                encoding="utf-8",
            )
            secrets = helpers.load_secrets(secrets_path)

        self.assertEqual(secrets["voice_gateway"], {"enabled": True, "port": 49178})

    def test_build_voice_command_payload_summarizes_command(self):
        helpers = load_helpers()

        payload = helpers.build_voice_command_payload(
            {
                "type": "command",
                "intent": "play",
                "query": "Sandstorm",
                "raw": "DjGoo play Sandstorm",
            }
        )

        self.assertEqual(payload["username"], "DjGoo")
        description = payload["embeds"][0]["description"]
        self.assertIn("Play", payload["embeds"][0]["title"])
        self.assertIn("Sandstorm", description)
        self.assertIn("DjGoo play Sandstorm", description)
        self.assertNotIn("listening", description.lower())
        self.assertNotIn("wiring is next", description.lower())

    def test_parse_djgoo_chat_command_translates_wake_phrase_to_red_command(self):
        helpers = load_helpers()

        examples = {
            "DjGoo play Sandstorm": "play Sandstorm",
            "DJGOO PLAY SANDSTORM": "PLAY SANDSTORM",
            "DjGoo, skip": "skip",
            "DJGOO SKIP": "SKIP",
            "DJ stop": "stop",
            "DeeJay queue": "queue",
            "hey DjGoo volume 50": "volume 50",
        }

        for content, command in examples.items():
            with self.subTest(content=content):
                self.assertEqual(helpers.parse_djgoo_chat_command(content), command)

    def test_parse_djgoo_chat_command_ignores_casual_messages(self):
        helpers = load_helpers()

        self.assertIsNone(helpers.parse_djgoo_chat_command("that DJ was great"))
        self.assertIsNone(helpers.parse_djgoo_chat_command("play Sandstorm"))

    def test_playback_control_labels_are_available_for_button_views(self):
        helpers = load_helpers()

        labels = [button["label"] for button in helpers.PLAYBACK_CONTROL_BUTTONS]

        self.assertIn("Skip", labels)
        self.assertIn("Pause/Resume", labels)
        self.assertIn("Stop", labels)
        self.assertIn("Queue", labels)
        self.assertIn("Vol -", labels)
        self.assertIn("Vol +", labels)
        self.assertIn("Like", labels)
        self.assertIn("More Like", labels)
        self.assertIn("Less Like", labels)
        self.assertIn("Ban", labels)

    def test_build_playback_control_embed_mentions_buttons_without_audio_noise(self):
        helpers = load_helpers()

        embed = helpers.build_playback_control_embed(
            {"title": "Darude - Sandstorm", "uri": "https://example.test/sandstorm"},
            station_name="Sandstorm radio",
        )

        self.assertIn("Darude - Sandstorm", embed["title"])
        self.assertIn("Sandstorm radio", embed["description"])
        self.assertIn("buttons", embed["footer"]["text"].lower())
        self.assertNotIn("listen", embed["description"].lower())

    def test_build_station_track_payload_is_visual_only_and_glanceable(self):
        helpers = load_helpers()

        payload = helpers.build_station_track_payload(
            station_name="Sandstorm radio",
            track={"title": "Kernkraft 400", "uri": "https://example.test/kernkraft"},
            reason="Fresh similar pick",
        )

        self.assertEqual(payload["username"], "DjGoo")
        self.assertNotIn("content", payload)
        embed = payload["embeds"][0]
        self.assertIn("Kernkraft 400", embed["title"])
        self.assertIn("Sandstorm radio", embed["description"])
        self.assertIn("Fresh similar pick", embed["description"])
        self.assertIn("like this", embed["footer"]["text"])


if __name__ == "__main__":
    unittest.main()
