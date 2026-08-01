from __future__ import annotations

import os
import time
from pathlib import Path

from tools import djgoo_portable_stack


class _Core:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.records = {
            "redbot": {"pid": os.getpid()},
            "lavalink": {"pid": 4242, "create_time": 100.0},
        }
        self.heartbeats = {
            "redbot": {
                "pid": os.getpid(),
                "timestamp": time.time(),
                "ready": True,
                "event": "redbot.ready",
                "audio_loaded": True,
                "discord_ready": True,
            },
            "lavalink-client": {
                "pid": os.getpid(),
                "timestamp": time.time(),
                "ready": True,
                "node_count": 1,
                "ready_node_count": 1,
            },
        }

    def component_record(self, name: str):
        return self.records.get(name)

    def health_path(self, name: str) -> Path:
        return self.tmp_path / f"{name}.json"

    def read_json(self, path: Path):
        return self.heartbeats.get(path.stem)


def test_redbot_is_not_ready_until_lavalink_server_is_ready(
    tmp_path: Path, monkeypatch
) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(
        djgoo_portable_stack,
        "_portable_lavalink_ready",
        lambda _core: False,
    )
    monkeypatch.setattr(
        djgoo_portable_stack,
        "_lavalink_client_ready",
        lambda _core, _pid: True,
    )

    assert djgoo_portable_stack._portable_redbot_ready(core) is False


def test_open_lavalink_server_is_not_enough_without_red_client_node(
    tmp_path: Path, monkeypatch
) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(
        djgoo_portable_stack,
        "_portable_lavalink_ready",
        lambda _core: True,
    )
    core.heartbeats["lavalink-client"]["ready"] = False
    core.heartbeats["lavalink-client"]["ready_node_count"] = 0

    assert djgoo_portable_stack._portable_redbot_ready(core) is False


def test_redbot_ready_requires_real_red_lavalink_node(
    tmp_path: Path, monkeypatch
) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(
        djgoo_portable_stack,
        "_portable_lavalink_ready",
        lambda _core: True,
    )

    assert djgoo_portable_stack._portable_redbot_ready(core) is True


def test_stale_lavalink_client_heartbeat_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(
        djgoo_portable_stack,
        "_portable_lavalink_ready",
        lambda _core: True,
    )
    core.heartbeats["lavalink-client"]["timestamp"] = time.time() - 30

    assert djgoo_portable_stack._portable_redbot_ready(core) is False
