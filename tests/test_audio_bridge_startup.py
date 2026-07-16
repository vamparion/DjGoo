import importlib.util
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.djgoo_stations import DjGooStations


class FakeGuild:
    id = 123


class FakeContext:
    guild = FakeGuild()


class FakeAudio:
    command_play = object()
    command_stop = object()
    command_skip = object()


class FakeMember:
    bot = False


class FakeVoiceChannel:
    members = [FakeMember()]


class FakeTextChannel:
    pass


class FakeResumeGuild:
    id = 123
    voice_channels = [FakeVoiceChannel()]
    text_channels = [FakeTextChannel()]
    system_channel = None
    me = object()


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

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_station_skip_bans_track_from_radio(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Track:
            title = "Same Song"
            uri = "u:same"
            info = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.stations.set_active(FakeGuild.id, "Sandstorm")
            bridge._selected_track = lambda guild_id, last=False: Track()

            await bridge._mark_station_skip(FakeContext())

            station = bridge.stations.get_active(FakeGuild.id)

        self.assertEqual(station["skipped"][0]["title"], "Same Song")
        self.assertEqual(station["banned"][0]["title"], "Same Song")
        self.assertEqual(station["recent"][0]["title"], "Same Song")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_station_rejects_skipped_or_banned_track(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        station = {
            "banned": [{"title": "Blocked", "uri": "u:block"}],
            "skipped": [{"title": "Skipped", "uri": "u:skip"}],
            "less_like": [{"title": "Less", "uri": "u:less"}],
            "recent": [{"title": "Recent", "uri": "u:recent"}],
        }

        self.assertTrue(bridge._station_rejects_track(station, {"title": "Blocked", "uri": "u:block"}))
        self.assertTrue(bridge._station_rejects_track(station, {"title": "Skipped", "uri": "u:skip"}))
        self.assertTrue(bridge._station_rejects_track(station, {"title": "Less", "uri": "u:less"}))
        self.assertTrue(bridge._station_rejects_track(station, {"title": "Recent", "uri": "u:recent"}))
        self.assertFalse(bridge._station_rejects_track(station, {"title": "Fresh", "uri": "u:fresh"}))

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_station_rejects_obvious_non_song_titles(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        station = {"banned": [], "skipped": [], "recent": []}
        bad_titles = [
            "Metallica and Megadeth - Song Similarities",
            "Some Song instrumental",
            "Band interview clip",
            "90s greatest hits playlist",
            "Alternative Rock Of The 90s 2000s - Rock Music Collection",
            "Guitar lesson tutorial",
        ]

        for title in bad_titles:
            with self.subTest(title=title):
                self.assertTrue(bridge._station_rejects_track(station, {"title": title, "uri": f"u:{title}"}))

        self.assertFalse(
            bridge._station_rejects_track(
                station,
                {"title": "Metallica: Nothing Else Matters (Official Music Video)", "uri": "u:ok"},
            )
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_radio_start_resolves_seed_before_playing(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.notices = []
            bridge.played_queries = []

            async def notice(message):
                bridge.notices.append(message)

            async def resolve(query):
                return f"Resolved {query}"

            async def play_query_when_ready(audio, ctx, query):
                bridge.played_queries.append(query)
                return True

            async def send_controls(ctx):
                return None

            bridge._notice = notice
            bridge._resolve_radio_seed_query = resolve
            bridge._play_query_when_ready = play_query_when_ready
            bridge._send_controls_for_player = send_controls

            result = await bridge._start_radio(FakeAudio(), FakeContext(), "Rock")
            active_station = bridge.stations.get_active(FakeGuild.id)

        self.assertEqual(result, "Started Rock radio")
        self.assertEqual(bridge.played_queries, ["Resolved Rock"])
        self.assertEqual(active_station["seed"], "Rock")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_radio_skip_tops_up_station_after_skipping(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.stations.set_active(FakeGuild.id, "Rock")
            bridge.invoked = []
            bridge.topped_up = []

            async def invoke(command, ctx, *args, **kwargs):
                bridge.invoked.append(command)

            async def top_up(guild_id):
                bridge.topped_up.append(guild_id)

            bridge._invoke = invoke
            bridge._top_up_station_queue = top_up

            await bridge._skip_playback(FakeAudio(), FakeContext())

        self.assertEqual(bridge.invoked, [FakeAudio.command_skip])
        self.assertEqual(bridge.topped_up, [FakeGuild.id])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_radio_fallback_query_uses_nuclear_before_search_text(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return f"Nuclear {query}"

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()

        self.assertEqual(await bridge._radio_fallback_query("Rock"), "Nuclear rock hits")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_radio_fallback_expands_broad_station_seed_for_nuclear(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return f"Nuclear {query}"

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()

        self.assertEqual(await bridge._radio_fallback_query("80s"), "Nuclear 80s hits")
        self.assertEqual(await bridge._radio_fallback_query("white girl music"), "Nuclear 2000s pop hits")
        self.assertEqual(await bridge._radio_fallback_query("Sandstorm"), "Nuclear Sandstorm")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resume_active_radio_starts_station_without_notice(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Bot:
            guilds = [FakeResumeGuild()]

            def get_cog(self, name):
                return FakeAudio()

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.bot = Bot()
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.stations.set_active(FakeGuild.id, "80s")
            bridge.played_queries = []
            bridge.notices = []

            async def play_query_when_ready(audio, ctx, query):
                bridge.played_queries.append(query)
                return True

            async def notice(message):
                bridge.notices.append(message)

            bridge._best_text_channel = lambda guild: FakeTextChannel()
            bridge._player_has_music = lambda guild_id: False
            async def radio_fallback_query(seed):
                return "Nuclear 80s hits"

            bridge._radio_fallback_query = radio_fallback_query
            bridge._play_query_when_ready = play_query_when_ready
            bridge._notice = notice
            bridge._send_payload = lambda payload: None

            with patch.dict("os.environ", {"DJGOO_RESUME_ACTIVE_RADIO": "1"}):
                await bridge.resume_active_radio_stations()

        self.assertEqual(bridge.played_queries, ["Nuclear 80s hits"])
        self.assertEqual(bridge.notices, [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resume_active_radio_does_nothing_without_restart_flag(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.played_queries = []

        async def play_query_when_ready(audio, ctx, query):
            bridge.played_queries.append(query)

        bridge._play_query_when_ready = play_query_when_ready

        with patch.dict("os.environ", {}, clear=True):
            await bridge.resume_active_radio_stations()

        self.assertEqual(bridge.played_queries, [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_radio_search_query_avoids_similarity_wording_and_excludes_junk(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        query = bridge._radio_search_query("Metallica")

        self.assertIn("Metallica official music video", query)
        self.assertNotIn("similar music", query)
        self.assertIn("-instrumental", query)
        self.assertIn("-clip", query)
        self.assertIn("-playlist", query)

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_radio_recommendation_picks_clean_song_candidate(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        station = {
            "banned": [],
            "skipped": [],
            "recent": [{"title": "Metallica - Nothing Else Matters", "uri": "https://www.youtube.com/watch?v=tAGnKpE4NCI"}],
        }
        tracks = [
            {"videoId": "tAGnKpE4NCI", "title": "Nothing Else Matters", "length": "6:26", "artists": [{"name": "Metallica"}]},
            {"videoId": "AAAAAAAAAAA", "title": "Metallica Song Similarities", "length": "5:00", "artists": [{"name": "Uploader"}]},
            {"videoId": "BBBBBBBBBBB", "title": "Four Hour Metal Mix", "length": "4:00:00", "artists": [{"name": "Uploader"}]},
            {"videoId": "DDGhKS6bSAE", "title": "The Unforgiven", "length": "6:24", "artists": [{"name": "Metallica"}]},
        ]

        picked = bridge._pick_recommended_track(station, tracks)

        self.assertEqual(picked["title"], "Metallica - The Unforgiven")
        self.assertEqual(picked["uri"], "https://www.youtube.com/watch?v=DDGhKS6bSAE")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_youtube_video_id_and_length_helpers(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        self.assertEqual(bridge._youtube_video_id("https://www.youtube.com/watch?v=tAGnKpE4NCI"), "tAGnKpE4NCI")
        self.assertEqual(bridge._youtube_video_id("https://youtu.be/tAGnKpE4NCI"), "tAGnKpE4NCI")
        self.assertEqual(bridge._track_length_seconds("6:24"), 384)
        self.assertEqual(bridge._track_length_seconds("1:02:03"), 3723)
        self.assertEqual(bridge._duration_value_seconds(384000), 384)
        self.assertEqual(bridge._duration_value_seconds(384), 384)

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_overlong_tracks_are_rejected(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        self.assertTrue(
            bridge._should_reject_playing_track(
                {"title": "System Of A Down full album", "uri": "u:album", "duration_seconds": "3600"}
            )
        )
        self.assertTrue(
            bridge._should_reject_playing_track(
                {"title": "Normal looking title", "uri": "u:long", "duration_seconds": "1200"}
            )
        )
        self.assertTrue(
            bridge._should_reject_playing_track(
                {"title": "Toto - Africa [10 Hour]", "uri": "u:ten-hour"}
            )
        )
        self.assertFalse(
            bridge._should_reject_playing_track(
                {"title": "Metallica - One", "uri": "u:song", "duration_seconds": "447"}
            )
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_track_data_includes_duration_when_available(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Track:
            title = "Song"
            uri = "u:song"
            length = 245000
            info = {}

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        self.assertEqual(bridge._track_data(Track())["duration_seconds"], "245")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    def test_controls_track_lookup_prefers_current_song_over_queue(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Player:
            current = "current song"
            queue = ["queued song"]

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        with patch("local_cogs.djgoowelcome.audio_bridge.lavalink.get_player", return_value=Player()):
            self.assertEqual(bridge._track_from_player_for_controls(FakeGuild.id), "current song")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_enqueue_event_does_not_post_now_playing_controls(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.sent = []

        async def send_playback_controls(*args, **kwargs):
            bridge.sent.append((args, kwargs))

        bridge._send_playback_controls = send_playback_controls

        await bridge.handle_track_enqueue(FakeGuild(), object())

        self.assertEqual(bridge.sent, [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_uses_nuclear_when_available(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return f"Resolved {query}"

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()

        self.assertEqual(await bridge._resolve_play_query("song"), "Resolved song")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_falls_back_to_original_query(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return None

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()

        self.assertEqual(await bridge._resolve_play_query("song"), "song")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_play_album_queues_resolved_album_tracks(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_album_queries(self, query):
                return ["Artist - One official audio", "Artist - Two official audio"]

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()
        bridge.notices = []
        bridge.invoked = []

        async def notice(message):
            bridge.notices.append(message)

        async def invoke(command, ctx, *args, **kwargs):
            bridge.invoked.append(kwargs["query"])

        bridge._notice = notice
        bridge._invoke = invoke

        result = await bridge._play_album(FakeAudio(), FakeContext(), "Album")

        self.assertEqual(result, "Queued album Album")
        self.assertEqual(bridge.invoked, ["Artist - One official audio", "Artist - Two official audio"])


if __name__ == "__main__":
    unittest.main()
