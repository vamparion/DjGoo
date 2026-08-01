from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from local_cogs.djgoowelcome.resilient_game_first_bridge import (
    ResilientGameFirstDjGooAudioBridge,
)


def _bridge(root: Path) -> ResilientGameFirstDjGooAudioBridge:
    bridge = object.__new__(ResilientGameFirstDjGooAudioBridge)
    bridge.project_root = root
    bridge.playback_state_path = root / "data" / "djgoo-playback-state.json"
    return bridge


def test_saved_playback_state_enables_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DJGOO_RESUME_PLAYBACK", raising=False)
    monkeypatch.delenv("DJGOO_RESUME_ACTIVE_RADIO", raising=False)
    bridge = _bridge(tmp_path)
    bridge.playback_state_path.parent.mkdir(parents=True)
    bridge.playback_state_path.write_text('{"guilds": {"42": {}}}', encoding="utf-8")

    assert bridge._should_resume_playback() is True


def test_stale_playback_state_does_not_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DJGOO_RESUME_PLAYBACK", raising=False)
    monkeypatch.delenv("DJGOO_RESUME_ACTIVE_RADIO", raising=False)
    bridge = _bridge(tmp_path)
    bridge.playback_state_path.parent.mkdir(parents=True)
    bridge.playback_state_path.write_text('{"guilds": {"42": {}}}', encoding="utf-8")
    stale = time.time() - 3600
    os.utime(bridge.playback_state_path, (stale, stale))

    assert bridge._should_resume_playback() is False


def test_active_sqlite_station_enables_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DJGOO_RESUME_PLAYBACK", raising=False)
    monkeypatch.delenv("DJGOO_RESUME_ACTIVE_RADIO", raising=False)
    bridge = _bridge(tmp_path)
    database = tmp_path / "data" / "djgoo-stations.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE active_stations (guild_id INTEGER PRIMARY KEY, station_id TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO active_stations VALUES (42, 'rock')")

    assert bridge._should_resume_playback() is True


def test_no_saved_session_does_not_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DJGOO_RESUME_PLAYBACK", raising=False)
    monkeypatch.delenv("DJGOO_RESUME_ACTIVE_RADIO", raising=False)
    bridge = _bridge(tmp_path)

    assert bridge._should_resume_playback() is False
