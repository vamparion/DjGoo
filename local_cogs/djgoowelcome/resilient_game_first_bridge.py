from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .game_first_audio_bridge import GameFirstDjGooAudioBridge


class ResilientGameFirstDjGooAudioBridge(GameFirstDjGooAudioBridge):
    """Resume a real saved session after process replacement or launcher restart."""

    def _should_resume_playback(self) -> bool:
        if super()._should_resume_playback():
            return True
        if self._playback_state_path().exists():
            return True
        root = Path(getattr(self, "project_root", Path.cwd()))
        if self._sqlite_station_is_active(root / "data" / "djgoo-stations.sqlite3"):
            return True
        return self._legacy_station_is_active(root / "data" / "djgoo-stations.json")

    @staticmethod
    def _sqlite_station_is_active(path: Path) -> bool:
        if not path.exists():
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

    @staticmethod
    def _legacy_station_is_active(path: Path) -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        active = payload.get("active") if isinstance(payload, dict) else None
        return isinstance(active, dict) and bool(active)
