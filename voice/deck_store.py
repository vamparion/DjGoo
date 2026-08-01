from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class DeckStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        decks = payload.get("decks", {}) if isinstance(payload, dict) else {}
        return decks if isinstance(decks, dict) else {}

    def get(self, guild_id: int) -> dict[str, Any] | None:
        with self._lock:
            value = self._read().get(str(int(guild_id)))
        return dict(value) if isinstance(value, dict) else None

    def set(self, guild_id: int, *, channel_id: int, message_id: int) -> None:
        with self._lock:
            decks = self._read()
            decks[str(int(guild_id))] = {
                "channel_id": int(channel_id),
                "message_id": int(message_id),
            }
            self._write(decks)

    def clear(self, guild_id: int) -> None:
        with self._lock:
            decks = self._read()
            decks.pop(str(int(guild_id)), None)
            self._write(decks)

    def _write(self, decks: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps({"schema": 1, "decks": decks}, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)
