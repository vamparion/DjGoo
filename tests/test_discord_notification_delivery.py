from __future__ import annotations

import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
class DiscordNotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_channel_delivery_does_not_need_webhook(self) -> None:
        from local_cogs.djgoowelcome.djgoowelcome import DjGooWelcome

        sent = []

        class Channel:
            id = 456

            async def send(self, **kwargs):
                sent.append(kwargs)

        guild = SimpleNamespace(id=123)
        cog = DjGooWelcome.__new__(DjGooWelcome)
        cog.bot = SimpleNamespace(guilds=[guild])
        cog._audio_bridge = SimpleNamespace(_best_text_channel=lambda _guild: Channel())

        delivered = await cog._send_bot_payload(
            {
                "content": "DjGoo: Skipping.",
                "embeds": [{"title": "Skipping", "description": "Heard it."}],
            }
        )

        self.assertTrue(delivered)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["embeds"][0].title, "Skipping")


@unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
class DiscordDeckDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_track_events_render_once(self) -> None:
        from local_cogs.djgoowelcome.experience_audio_bridge import ExperienceDjGooAudioBridge

        sent = []

        class Message:
            id = 789

        class Channel:
            id = 456

            def permissions_for(self, _member):
                return SimpleNamespace(send_messages=True)

            async def send(self, **kwargs):
                sent.append(kwargs)
                return Message()

        class DeckStore:
            def __init__(self):
                self.record = None

            def get(self, _guild_id):
                return self.record

            def set(self, _guild_id, *, channel_id, message_id):
                self.record = {"channel_id": channel_id, "message_id": message_id}

            def clear(self, _guild_id):
                self.record = None

        channel = Channel()
        guild = SimpleNamespace(id=123, me=object(), get_channel=lambda _id: channel)
        track = SimpleNamespace(track_identifier="track-1", title="Test Song")
        bridge = ExperienceDjGooAudioBridge.__new__(ExperienceDjGooAudioBridge)
        bridge._deck_locks = {}
        bridge._deck_render_state = {}
        bridge.deck_store = DeckStore()
        bridge.stations = SimpleNamespace(get_active=lambda _guild_id: None)
        bridge._track_data = lambda _track: {
            "title": "Test Song",
            "artist": "Test Artist",
            "uri": "https://www.youtube.com/watch?v=abcdefghijk",
            "duration_seconds": "180",
        }
        bridge._should_reject_playing_track = lambda _data: False
        bridge._best_text_channel = lambda _guild: channel
        bridge._mode_for_track = lambda _guild_id, _track: "PLAYBACK"
        bridge._active_request_details = lambda _guild_id: {}
        bridge._queue_preview = lambda _guild_id: []
        bridge._tip_for_track = lambda _track, radio_active: "Try saying: skip"
        bridge._track_key = lambda _track: "track-1"

        await bridge._send_playback_controls(guild, track)
        await bridge._send_playback_controls(guild, track, force=True)

        self.assertEqual(len(sent), 1)
