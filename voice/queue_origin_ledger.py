from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class QueueOriginLedger:
    """Persist non-manual queue provenance without owning queue order."""

    def __init__(self, path: Path, *, max_age_seconds: float = 12 * 60 * 60) -> None:
        self.path = path
        self.max_age_seconds = float(max_age_seconds)
        self._lock = threading.RLock()

    def add(
        self,
        guild_id: int,
        *,
        track_key: str,
        source: str,
        label: str = "",
    ) -> None:
        if not track_key:
            return
        with self._lock:
            data = self._read()
            entries = data.setdefault(str(int(guild_id)), [])
            entries.append(
                {
                    "track_key": str(track_key),
                    "source": str(source),
                    "label": str(label)[:100],
                    "created_at": time.time(),
                }
            )
            del entries[:-300]
            self._write(data)

    def entries(self, guild_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._read().get(str(int(guild_id)), [])]

    def consume(self, guild_id: int, track_key: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            entries = data.get(str(int(guild_id)), [])
            selected = None
            retained = []
            for entry in entries:
                if selected is None and str(entry.get("track_key") or "") == track_key:
                    selected = entry
                else:
                    retained.append(entry)
            if retained:
                data[str(int(guild_id))] = retained
            else:
                data.pop(str(int(guild_id)), None)
            self._write(data)
            return dict(selected) if selected else None

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        guilds = payload.get("guilds", {}) if isinstance(payload, dict) else {}
        now = time.time()
        return {
            str(guild_id): [
                dict(item)
                for item in entries
                if isinstance(item, dict)
                and now - float(item.get("created_at") or 0)
                <= self.max_age_seconds
            ]
            for guild_id, entries in guilds.items()
            if isinstance(entries, list)
        }

    def _write(self, guilds: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"schema": 1, "guilds": guilds},
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
