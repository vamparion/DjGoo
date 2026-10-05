import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_panel.server import create_handler_class


class ControlPanelServerTests(unittest.TestCase):
    def test_health_route_is_constant_time_service_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler_cls = create_handler_class(Path(temp_dir))

            status, body = handler_cls.route_get("/api/healthz")

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "djgoo-control-panel")

    def test_route_state_returns_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_get("/api/state")

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("state", body)

    def test_route_command_rejects_bad_json_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_post("/api/command", {"action": "bad"})

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_route_command_accepts_skip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_post("/api/command", {"action": "skip"})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["intent"], "skip")

    def test_local_skip_is_always_an_immediate_host_control(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, member = handler_cls.route_post(
                "/api/profile",
                {"username": "Old Browser", "device_id": "old"},
                is_local=False,
            )

            status, body = handler_cls.route_post(
                "/api/command",
                {"action": "skip", "token": member["profile"]["token"]},
                is_local=True,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["actor_role"], "host")
        self.assertEqual(body["item"]["intent"], "skip")

    def test_remote_member_skip_remains_a_member_vote(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, member = handler_cls.route_post(
                "/api/profile",
                {"username": "Remote Player", "device_id": "phone"},
                is_local=False,
            )

            status, body = handler_cls.route_post(
                "/api/command",
                {"action": "skip", "token": member["profile"]["token"]},
                is_local=False,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["actor_role"], "member")

    def test_music_search_returns_ranked_choices(self):
        expected = [
            {
                "title": "Ich Will",
                "artist": "Rammstein",
                "uri": "https://example.invalid/track",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            handler_cls = create_handler_class(Path(temp_dir))
            with patch("control_panel.server.search_music_candidates", return_value=expected) as search:
                status, body = handler_cls.route_get("/api/music/search?q=ich%20will")

        self.assertEqual(status, 200)
        self.assertEqual(body["results"], expected)
        search.assert_called_once_with("ich will")

    def test_music_search_requires_a_query(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler_cls = create_handler_class(Path(temp_dir))
            status, body = handler_cls.route_get("/api/music/search")

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_local_first_profile_is_host_and_can_update_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_post(
                "/api/profile",
                {"username": "Vera", "device_id": "desktop"},
                is_local=True,
            )
            profile = body["profile"]
            settings_status, settings_body = handler_cls.route_post(
                "/api/settings",
                {"token": profile["token"], "settings": {"ranked_mode": True}},
            )

        self.assertEqual(status, 200)
        self.assertEqual(profile["role"], "host")
        self.assertEqual(settings_status, 200)
        self.assertTrue(settings_body["settings"]["ranked_mode"])

    def test_remote_member_cannot_change_host_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, body = handler_cls.route_post(
                "/api/profile",
                {"username": "Player Two", "device_id": "phone"},
                is_local=False,
            )

            status, response = handler_cls.route_post(
                "/api/settings",
                {"token": body["profile"]["token"], "settings": {"ranked_mode": True}},
            )

        self.assertEqual(status, 400)
        self.assertFalse(response["ok"])
        self.assertIn("host", response["error"].lower())

    def test_local_browser_can_resume_existing_profile_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler_cls = create_handler_class(Path(temp_dir))
            _, first = handler_cls.route_post(
                "/api/profile", {"username": "Oinky", "device_id": "old-browser"}, is_local=True
            )
            status, resumed = handler_cls.route_post(
                "/api/profile", {"username": "Oinky", "device_id": "new-browser"}, is_local=True
            )

        self.assertEqual(status, 200)
        self.assertEqual(resumed["profile"]["id"], first["profile"]["id"])
        self.assertEqual(resumed["profile"]["token"], first["profile"]["token"])

    def test_remote_browser_cannot_claim_existing_profile_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler_cls = create_handler_class(Path(temp_dir))
            handler_cls.route_post(
                "/api/profile", {"username": "Oinky", "device_id": "owner"}, is_local=True
            )
            status, response = handler_cls.route_post(
                "/api/profile", {"username": "Oinky", "device_id": "remote"}, is_local=False
            )

        self.assertEqual(status, 400)
        self.assertIn("already in use", response["error"])

    def test_host_can_delete_playlist_and_station_but_member_cannot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, host_body = handler_cls.route_post(
                "/api/profile", {"username": "Host", "device_id": "host"}, is_local=True
            )
            _, member_body = handler_cls.route_post(
                "/api/profile", {"username": "Member", "device_id": "member"}, is_local=False
            )
            from voice.djgoo_playlists import DjGooPlaylists
            from voice.sqlite_stations import SqliteDjGooStations
            DjGooPlaylists(root / "data" / "djgoo-playlists.json").create("Game Night")
            SqliteDjGooStations(root / "data" / "djgoo-stations.sqlite3").get_or_create("Rock")

            denied, denied_body = handler_cls.route_post(
                "/api/playlist/delete",
                {"token": member_body["profile"]["token"], "playlist": "Game Night"},
            )
            playlist_status, _ = handler_cls.route_post(
                "/api/playlist/delete",
                {"token": host_body["profile"]["token"], "playlist": "Game Night"},
            )
            station_status, _ = handler_cls.route_post(
                "/api/station/delete",
                {"token": host_body["profile"]["token"], "seed": "Rock"},
            )
            gc.collect()

        self.assertEqual(denied, 400)
        self.assertIn("moderator", denied_body["error"])
        self.assertEqual(playlist_status, 200)
        self.assertEqual(station_status, 200)

    def test_host_can_add_one_recent_song_to_a_playlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, host = handler_cls.route_post(
                "/api/profile", {"username": "Host", "device_id": "desktop"}, is_local=True
            )
            from voice.djgoo_playlists import DjGooPlaylists
            from voice.mini_player_protocol import MiniPlayerHistory

            playlists = DjGooPlaylists(root / "data" / "djgoo-playlists.json")
            playlists.create("Game Night")
            history = MiniPlayerHistory(root / "data" / "djgoo-mini-history.json")
            history.add(
                {"id": "recent-1", "title": "Recent Song", "artist": "Artist", "uri": "https://example.invalid/song"},
                mode="PLAYBACK",
            )

            status, body = handler_cls.route_post(
                "/api/playlist/history-add",
                {"token": host["profile"]["token"], "playlist": "Game Night", "track_id": "recent-1"},
                is_local=True,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["added"], 1)

    def test_host_can_create_a_playlist_for_history_drop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)
            _, host = handler_cls.route_post(
                "/api/profile", {"username": "Host", "device_id": "desktop"}, is_local=True
            )

            status, body = handler_cls.route_post(
                "/api/playlist/create",
                {"token": host["profile"]["token"], "playlist": "New Mix"},
                is_local=True,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["result"], {"name": "new mix", "created": True})


if __name__ == "__main__":
    unittest.main()
