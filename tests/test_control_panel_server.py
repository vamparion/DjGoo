import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
