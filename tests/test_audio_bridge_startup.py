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
            bridge.playback_state_path = Path(temp_dir) / "playback-state.json"
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
    async def test_radio_start_activates_station_and_saves_exact_seed_before_playing(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")

            async def resolve(_query):
                return "https://www.youtube.com/watch?v=YFtrq9vy9UM"

            async def play_query_when_ready(_audio, ctx, _query):
                station = bridge.stations.get_active(ctx.guild.id)
                self.assertIsNotNone(station)
                self.assertEqual(station["seed_track"]["uri"], "https://www.youtube.com/watch?v=YFtrq9vy9UM")
                return True

            async def no_op(*_args, **_kwargs):
                return None

            bridge._resolve_radio_seed_query = resolve
            bridge._play_query_when_ready = play_query_when_ready
            bridge._notice = no_op
            bridge._send_controls_for_player = no_op

            result = await bridge._start_radio(FakeAudio(), FakeContext(), "The Death and Resurrection Show")

        self.assertEqual(result, "Started The Death And Resurrection Show radio")

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
    def test_radio_recommendation_rejects_remixes_and_dubs(self):
        from local_cogs.djgoowelcome.enhanced_audio_bridge import EnhancedDjGooAudioBridge

        bridge = EnhancedDjGooAudioBridge.__new__(EnhancedDjGooAudioBridge)
        station = {"seed": "Song", "mode": "balanced", "banned": [], "recent": []}
        tracks = [
            {"videoId": "AAAAAAAAAAA", "title": "Song (Long Remix)", "duration": "8:00", "artists": [{"name": "Artist"}]},
            {"videoId": "BBBBBBBBBBB", "title": "Song Ambient Dub", "duration": "5:00", "artists": [{"name": "Artist"}]},
            {"videoId": "CCCCCCCCCCC", "title": "Related Song", "duration": "4:00", "artists": [{"name": "Band"}]},
        ]

        picked = bridge._pick_recommended_track(station, tracks)

        self.assertEqual(picked["uri"], "https://www.youtube.com/watch?v=CCCCCCCCCCC")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_youtube_playlist_uses_strict_playlist_page_before_metadata_fallback(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        calls = []

        def strict(playlist_id):
            calls.append(("strict", playlist_id))
            return [{"videoId": "AAAAAAAAAAA", "title": "Exact playlist song", "duration_seconds": 210}]

        def fallback(_playlist_id):
            calls.append(("fallback", _playlist_id))
            return [{"videoId": "BBBBBBBBBBB", "title": "Wrong playlist song", "duration_seconds": 220}]

        bridge._ytdlp_playlist_tracks = strict
        bridge._ytmusic_playlist_tracks = fallback

        tracks = await bridge._youtube_playlist_tracks("PLrequested")

        self.assertEqual([track["videoId"] for track in tracks], ["AAAAAAAAAAA"])
        self.assertEqual(calls, [("strict", "PLrequested")])

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
    async def test_rejected_track_start_skips_without_controls(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            class Track:
                title = "Toto - Africa [10 Hour]"
                uri = "https://www.youtube.com/watch?v=EiOgy4AWPkg"
                length = 36093000
                info = {}

            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.skips = []
            bridge.controls = []
            bridge._persist_player_state = lambda *args, **kwargs: None

            async def skip_rejected(guild_id, *, top_up_station=False):
                bridge.skips.append((guild_id, top_up_station))

            async def send_controls(*args, **kwargs):
                bridge.controls.append((args, kwargs))

            bridge._skip_rejected_track = skip_rejected
            bridge._send_playback_controls = send_controls

            await bridge.handle_track_start(FakeGuild(), Track())

        self.assertEqual(bridge.skips, [(FakeGuild.id, False)])
        self.assertEqual(bridge.controls, [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_rejected_track_bypasses_vote_skip_and_advances_player_directly(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Player:
            def __init__(self):
                self.skip_count = 0

            def skip(self):
                self.skip_count += 1

        class Bot:
            def get_cog(self, name):
                return FakeAudio() if name == "Audio" else None

        player = Player()
        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.bot = Bot()
        bridge._context = lambda: FakeContext()
        bridge.invocations = []

        async def invoke(*args, **kwargs):
            bridge.invocations.append((args, kwargs))

        bridge._invoke_silently = invoke

        with patch("local_cogs.djgoowelcome.audio_bridge.lavalink.get_player", return_value=player):
            await bridge._skip_rejected_track(FakeGuild.id)

        self.assertEqual(player.skip_count, 1)
        self.assertEqual(bridge.invocations, [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_visible_enqueue_for_rejected_current_track_skips(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            class Channel:
                id = 456

            class Message:
                guild = FakeGuild()
                channel = Channel()

            class Track:
                title = "Toto - Africa [10 Hour]"
                uri = "https://www.youtube.com/watch?v=EiOgy4AWPkg"
                length = 36093000
                info = {}

            bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
            bridge.stations = DjGooStations(Path(temp_dir) / "stations.json")
            bridge.skips = []
            bridge._current_track_for_controls = lambda guild_id: Track()

            async def skip_rejected(guild_id, *, top_up_station=False):
                bridge.skips.append((guild_id, top_up_station))

            bridge._skip_rejected_track = skip_rejected

            await bridge.handle_red_track_enqueue_message(Message())

        self.assertEqual(bridge.skips, [(FakeGuild.id, False)])

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
    async def test_playback_controls_send_visible_content_embed_and_buttons(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Perms:
            send_messages = True

        class Channel:
            id = 456
            sent = []

            def permissions_for(self, me):
                return Perms()

            async def send(self, **kwargs):
                self.sent.append(kwargs)

        class Guild:
            id = 123
            me = object()

        class Track:
            title = "Visible Song"
            uri = "https://example.test/song"
            length = 180000
            info = {}

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.stations = DjGooStations(Path(tempfile.mkdtemp()) / "stations.json")
        bridge._recent_control_posts = {}

        channel = Channel()

        await bridge._send_playback_controls(Guild(), Track(), preferred_channel=channel, force=True)

        self.assertEqual(len(channel.sent), 1)
        self.assertIn("Now playing: Visible Song", channel.sent[0]["content"])
        self.assertIsNotNone(channel.sent[0]["embed"])
        self.assertIsNotNone(channel.sent[0]["view"])

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
        bridge._ytmusic_song_search_query = lambda query: None

        self.assertEqual(await bridge._resolve_play_query("song"), "song")

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_voice_query_repairs_shadow_density_turn_off_to_lindsey_stirling(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return None

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()
        bridge._ytmusic_song_search_query = lambda query: f"resolved:{query}"

        self.assertEqual(
            await bridge._resolve_play_queries("shadow density turn off", source="voice"),
            ["resolved:Shadows Lindsey Stirling"],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_voice_query_blocks_raw_non_music_fallback_when_resolvers_fail(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return None

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()
        bridge._ytmusic_song_search_query = lambda query: None

        self.assertEqual(await bridge._resolve_play_queries("destiny settings turn off", source="voice"), [])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_uses_ytmusic_when_nuclear_returns_empty(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return None

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()
        bridge._ytmusic_song_search_query = lambda query: "https://www.youtube.com/watch?v=Xyvuu4dNAWc"

        self.assertEqual(
            await bridge._resolve_play_queries("Shadows by Lindy Stirling", source="voice"),
            ["https://www.youtube.com/watch?v=Xyvuu4dNAWc"],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_expands_real_youtube_playlist_to_individual_tracks(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        async def playlist(_playlist_id):
            return [
                {"videoId": "nVohJKUiK6o", "title": "Africa", "length": "4:55"},
                {"videoId": "AAAAAAAAAAA", "title": "Rosanna", "length": "5:31"},
                {"videoId": "BBBBBBBBBBB", "title": "Africa 10 Hour Loop", "duration_seconds": 36000},
                {"videoId": "nVohJKUiK6o", "title": "Africa duplicate", "length": "4:55"},
            ]

        bridge._youtube_playlist_tracks = playlist

        url = "https://www.youtube.com/watch?v=nVohJKUiK6o&list=PLFfDTu7b6FEBXlDz18cghi4zCcBVUN4Um"

        self.assertEqual(
            await bridge._resolve_play_queries(url),
            [
                "https://www.youtube.com/watch?v=nVohJKUiK6o",
                "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            ],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_pure_youtube_playlist_url_never_queues_opaque_playlist(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        async def playlist(_playlist_id):
            return []

        bridge._youtube_playlist_tracks = playlist

        self.assertEqual(
            await bridge._resolve_play_queries(
                "https://www.youtube.com/playlist?list=PLGQK9yb_7IyR4nhxGloR4YGKjhffi4RjR"
            ),
            [],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_markdown_youtube_playlist_uses_link_target(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        async def playlist(playlist_id):
            self.assertEqual(playlist_id, "PLreal_playlist")
            return [{"videoId": "AAAAAAAAAAA", "title": "Song", "length": "3:30"}]

        bridge._youtube_playlist_tracks = playlist
        query = (
            "[https://www.youtube.com/playlist?list=PLwrong\\_playlist]"
            "(https://www.youtube.com/playlist?list=PLreal_playlist)"
        )

        self.assertEqual(
            await bridge._resolve_play_queries(query),
            ["https://www.youtube.com/watch?v=AAAAAAAAAAA"],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_native_play_playlist_routes_through_djgoo_bridge(self):
        from local_cogs.djgoowelcome import _install_native_play_routing

        calls = []

        async def original(_audio, _ctx, *, query):
            calls.append(("original", query))

        class FakeCommand:
            callback = original

        class FakeBot:
            def __init__(self):
                self.command = FakeCommand()

            def get_command(self, name):
                return self.command if name == "play" else None

        class FakeBridge:
            _youtube_url_from_query = staticmethod(lambda query: query)
            _youtube_playlist_id = staticmethod(lambda query: "PLplaylist" if "playlist" in query else "")
            _is_real_youtube_playlist_id = staticmethod(lambda playlist_id: playlist_id.startswith("PL"))
            _configured_controls_channel = staticmethod(lambda guild: guild.voice_channels[0])

            async def handle_from_discord_context(self, item, ctx, voice_channel=None):
                calls.append(("bridge", item, ctx, voice_channel))
                return "queued"

        class FakeDjGoo:
            _audio_bridge = FakeBridge()

        class VoiceChannel:
            id = 456
            position = 0
            name = "Gaming"
            members = []

            async def connect(self):
                return None

        class Guild:
            voice_channels = [VoiceChannel()]

        class Author:
            id = 789
            voice = None

        class FakeContext:
            guild = Guild()
            channel = object()
            author = Author()

        bot = FakeBot()
        djgoo = FakeDjGoo()
        self.assertTrue(_install_native_play_routing(bot, djgoo))

        result = await bot.command.callback(
            object(),
            FakeContext(),
            query="https://www.youtube.com/playlist?list=PLplaylist",
        )

        self.assertEqual(result, "queued")
        self.assertEqual(calls[0][0], "bridge")
        self.assertEqual(calls[0][1]["intent"], "play")
        self.assertEqual(calls[0][3].id, 456)

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_discord_command_context_supplies_configured_voice_channel(self):
        from types import SimpleNamespace

        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        voice_channel = SimpleNamespace(id=456)
        author = SimpleNamespace(id=789, voice=None)
        discord_ctx = SimpleNamespace(guild=SimpleNamespace(id=123), author=author, channel=object())
        bridge._context_for = lambda guild, member, channel: SimpleNamespace(
            guild=guild,
            author=member,
            channel=channel,
        )

        async def handle(_item):
            return bridge._context()

        bridge.handle = handle
        result = await bridge.handle_from_discord_context({}, discord_ctx, voice_channel=voice_channel)

        self.assertEqual(result.guild.id, 123)
        self.assertEqual(result.author.id, 789)
        self.assertIs(result.author.voice.channel, voice_channel)

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_native_play_routing_preserves_red_command_parameters(self):
        import copy

        from redbot.cogs.audio.core.commands.player import PlayerCommands

        from local_cogs.djgoowelcome import _install_native_play_routing

        class FakeBot:
            def __init__(self):
                self.command = copy.copy(PlayerCommands.command_play)

            def get_command(self, name):
                return self.command if name == "play" else None

        class FakeDjGoo:
            _audio_bridge = object()

        bot = FakeBot()
        self.assertTrue(_install_native_play_routing(bot, FakeDjGoo()))
        self.assertEqual(list(bot.command.clean_params), ["query"])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_removes_dead_playlist_parameter(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)

        async def playlist(_playlist_id):
            return []

        bridge._youtube_playlist_tracks = playlist
        url = "https://www.youtube.com/watch?v=ZF5ElG1eKz0&list=PLGQK9yb_7IyR4nhxGloR4YGKjhffi4RjR&index=1"

        self.assertEqual(
            await bridge._resolve_play_queries(url),
            ["https://www.youtube.com/watch?v=ZF5ElG1eKz0"],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_expands_youtube_radio_url_into_clean_tracks(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge._ytmusic = None

        async def watch(video_id, playlist_id):
            return [
                {"videoId": "AAAAAAAAAAA", "title": "Good Song", "length": "3:30", "artists": [{"name": "Artist"}]},
                {"videoId": "BBBBBBBBBBB", "title": "Ten Hour Loop", "length": "10:00:00", "artists": [{"name": "Loop"}]},
                {"videoId": "CCCCCCCCCCC", "title": "Another Song", "length": "4:00", "artists": [{"name": "Band"}]},
            ]

        bridge._watch_playlist_tracks_for_url = watch
        url = "https://www.youtube.com/watch?v=nVohJKUiK6o&list=RDnVohJKUiK6o&start_radio=1"

        self.assertEqual(
            await bridge._resolve_play_queries(url),
            [
                "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                "https://www.youtube.com/watch?v=CCCCCCCCCCC",
            ],
        )

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_cleans_ten_hour_video_to_song_search(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def __init__(self):
                self.queries = []

            def resolve_track_query(self, query):
                self.queries.append(query)
                return "Artist - Sandstorm official audio"

        resolver = Resolver()
        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = resolver

        async def watch(video_id, playlist_id):
            return [
                {
                    "videoId": "AAAAAAAAAAA",
                    "title": "Sandstorm [10 Hour Loop]",
                    "length": "10:00:00",
                    "artists": [{"name": "Darude"}],
                }
            ]

        bridge._watch_playlist_tracks_for_url = watch

        self.assertEqual(
            await bridge._resolve_play_queries("https://www.youtube.com/watch?v=AAAAAAAAAAA"),
            ["Artist - Sandstorm official audio"],
        )
        self.assertEqual(resolver.queries, ["Darude - Sandstorm"])

    @unittest.skipUnless(importlib.util.find_spec("redbot"), "Redbot is only installed in the bot venv")
    async def test_resolve_play_query_expands_playlist_found_for_full_album_video(self):
        from local_cogs.djgoowelcome.audio_bridge import DjGooAudioBridge

        class Resolver:
            def resolve_track_query(self, query):
                return "Should not need single track fallback"

        bridge = DjGooAudioBridge.__new__(DjGooAudioBridge)
        bridge.nuclear = Resolver()

        async def watch(video_id, playlist_id):
            return [
                {
                    "videoId": "AAAAAAAAAAA",
                    "title": "Best Rock Album Full Album",
                    "length": "1:10:00",
                    "artists": [{"name": "Various Artists"}],
                }
            ]

        async def playlist(title):
            return "https://www.youtube.com/playlist?list=PLcleanAlbumTracks"

        async def playlist_tracks(playlist_id):
            return [
                {"videoId": "BBBBBBBBBBB", "title": "First Song", "length": "3:20"},
                {"videoId": "CCCCCCCCCCC", "title": "Second Song", "length": "4:10"},
            ]

        bridge._watch_playlist_tracks_for_url = watch
        bridge._resolve_dirty_youtube_playlist = playlist
        bridge._youtube_playlist_tracks = playlist_tracks

        self.assertEqual(
            await bridge._resolve_play_queries("https://www.youtube.com/watch?v=AAAAAAAAAAA"),
            [
                "https://www.youtube.com/watch?v=BBBBBBBBBBB",
                "https://www.youtube.com/watch?v=CCCCCCCCCCC",
            ],
        )

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
