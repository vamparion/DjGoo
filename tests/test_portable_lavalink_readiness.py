from __future__ import annotations

import os
import time
from pathlib import Path

from tools import djgoo_portable_stack


class _Core:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def component_record(self, name: str):
        assert name == "redbot"
        return {"pid": os.getpid()}

    def health_path(self, name: str) -> Path:
        assert name == "redbot"
        return self.tmp_path / "redbot.json"

    def read_json(self, path: Path):
        assert path == self.tmp_path / "redbot.json"
        return {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "ready": True,
            "event": "redbot.ready",
            "audio_loaded": True,
            "discord_ready": True,
        }


def test_redbot_is_not_ready_until_lavalink_port_listens(tmp_path: Path, monkeypatch) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(djgoo_portable_stack, "_lavalink_port_ready", lambda: False)

    assert djgoo_portable_stack._portable_redbot_ready(core) is False


def test_redbot_ready_accepts_live_lavalink_listener(tmp_path: Path, monkeypatch) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(djgoo_portable_stack, "_lavalink_port_ready", lambda: True)

    assert djgoo_portable_stack._portable_redbot_ready(core) is True
