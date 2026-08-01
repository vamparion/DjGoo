from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .game_first_audio_bridge import GameFirstDjGooAudioBridge


RECOVERY_SESSION_MAX_AGE_SECONDS = 30 * 60


class ResilientGameFirstDjGooAudioBridge(GameFirstDjGooAudioBridge):
    """Resume a recent saved session after process replacement or launcher restart."""

    def _should_resume_playback(self) -> bool:
        if super()._should_resume_playback():
            return True
        if self._recent_playback_state(self._playback_state_path()):
            return True
        root = Path(getattr(self, "project_root", Path.cwd()))
        if self._sqlite_station_is_active(root / "data" / "djgoo-stations.sqlite3"):
            return True
        return self._legacy_station_is_active(root / "data" / "djgoo-stations.json")

    @staticmethod
    def _path_is_recent(path: Path) -> bool:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return -5.0 <= age <= RECOVERY_SESSION_MAX_AGE_SECONDS

    @classmethod
    def _recent_playback_state(cls, path: Path) -> bool:
        if not cls._path_is_recent(path):
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        guilds = payload.get("guilds") if isinstance(payload, dict) else None
        return isinstance(guilds, dict) and bool(guilds)

    @classmethod
    def _sqlite_station_is_active(cls, path: Path) -> bool:
        related_paths = (path, Path(str(path) + "-wal"))
        if not any(cls._path_is_recent(candidate) for candidate in related_paths):
            return False
        try:
            with sqlite3.connect(
                f"file:{path.resolve().as_posix()}?mode=ro",
                uri=True,
                timeout=1,
            ) as connection:
                row = connection.execute(
                    "SELECT 1 FROM active_stations LIMIT 1"
                ).fetchone()
        except (OSError, sqlite3.Error):
            return False
        return row is not None

    @classmethod
    def _legacy_station_is_active(cls, path: Path) -> bool:
        if not cls._path_is_recent(path):
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        active = payload.get("active") if isinstance(payload, dict) else None
        return isinstance(active, dict) and bool(active)
