from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping


class NowPlayingState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def publish(self, guild_id: int, payload: Mapping[str, Any]) -> None:
        with self._lock:
            state = self.read_all()
            previous_order = max(
                (
                    int(item.get("updated_at_ns") or 0)
                    for item in state.values()
                    if isinstance(item, dict)
                ),
                default=0,
            )
            updated_at_ns = max(time.time_ns(), previous_order + 1)
            state[str(int(guild_id))] = {
                "guild_id": int(guild_id),
                "updated_at": updated_at_ns / 1_000_000_000,
                "updated_at_ns": updated_at_ns,
                **dict(payload),
            }
            self._write(state)

    def clear(self, guild_id: int) -> None:
        with self._lock:
            state = self.read_all()
            state.pop(str(int(guild_id)), None)
            self._write(state)

    def read_all(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        guilds = payload.get("guilds", {}) if isinstance(payload, dict) else {}
        return guilds if isinstance(guilds, dict) else {}

    def latest(self) -> dict[str, Any] | None:
        values = [value for value in self.read_all().values() if isinstance(value, dict)]
        if not values:
            return None
        return max(
            values,
            key=lambda item: (
                int(item.get("updated_at_ns") or 0),
                float(item.get("updated_at") or 0),
            ),
        )

    def _write(self, state: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps({"schema": 1, "guilds": state}, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)
