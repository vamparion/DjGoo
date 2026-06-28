import tempfile
import unittest
from pathlib import Path

from control_panel.server import create_handler_class


class ControlPanelServerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
