import importlib.util
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.djgoo_stations import DjGooStations


class FakeGuild:
    id = 123


class FakeContext:
    guild = FakeGuild()


class FakeAudio:
    command_play = object()
    command_stop = object()


class RadioStartupTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_radio_does_not_become_active_when_initial_play_never_queues(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.notices = []

            async def notice(message):
                bridge.notices.append(message)

            async def play_query_when_ready(audio, ctx, query):
                return False

            async def invoke(command, ctx, *args, **kwargs):
                return None

            bridge._notice = notice
            bridge._invoke = invoke
            bridge._play_query_when_ready = play_query_when_ready

            result = await bridge._start_radio(FakeAudio(), FakeContext(), "Robert Palmer")

        self.assertEqual(result, "Radio startup failed")
        self.assertIsNone(bridge.stations.get_active(FakeGuild.id))
        self.assertTrue(any("warming up" in message.lower() for message in bridge.notices))
        self.assertFalse(any("Started" in message for message in bridge.notices))

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_stop_playback_clears_active_radio_station(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.stations.set_active(FakeGuild.id, "Sandstorm")
            bridge.notices = []
            bridge.invoked = []

            async def notice(message):
                bridge.notices.append(message)

            async def invoke(command, ctx, *args, **kwargs):
                bridge.invoked.append(command)

            bridge._notice = notice
            bridge._invoke = invoke

            result = await bridge._stop_playback(FakeAudio(), FakeContext())

        self.assertEqual(result, "Stopped")
        self.assertIsNone(bridge.stations.get_active(FakeGuild.id))
        self.assertEqual(bridge.invoked, [FakeAudio.command_stop])
        self.assertTrue(any("turned off" in message for message in bridge.notices))

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_playback_buttons_are_persistent_after_restart(self):
        from local_cogs.djgoowelcome.audio_bridge import PlaybackControlsView

        view = PlaybackControlsView(bridge=object(), guild_id=0)

        self.assertIsNone(view.timeout)
        self.assertTrue(all(getattr(child, "custom_id", "").startswith("djgoo:") for child in view.children))


if __name__ == "__main__":
    unittest.main()
