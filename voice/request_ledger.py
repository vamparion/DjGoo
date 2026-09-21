from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class RequestLedger:
    """Persist request classification without becoming queue authority."""

    def __init__(self, path: Path, *, max_age_seconds: float = 6 * 60 * 60) -> None:
        self.path = path
        self.max_age_seconds = float(max_age_seconds)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        guilds = payload.get("guilds", {}) if isinstance(payload, dict) else {}
        if not isinstance(guilds, dict):
            return {}
        now = time.time()
        cleaned: dict[str, list[dict[str, Any]]] = {}
        for guild_id, entries in guilds.items():
            if not isinstance(entries, list):
                continue
            current = [
                entry
                for entry in entries
                if isinstance(entry, dict)
                and now - float(entry.get("created_at") or 0) <= self.max_age_seconds
            ]
            if current:
                cleaned[str(guild_id)] = current
        return cleaned

    def add(
        self,
        guild_id: int,
        *,
        track_key: str,
        title: str,
        timing: str,
        requester_id: int | None = None,
        requester_name: str = "",
        entry_id: str = "",
        lane: str = "request",
        insertion_reason: str = "manual request",
        source: str = "unknown",
        requester_key: str = "",
    ) -> None:
        if not track_key:
            return
        with self._lock:
            guilds = self._read()
            entries = guilds.setdefault(str(int(guild_id)), [])
            entries.append(
                {
                    "track_key": track_key,
                    "title": title,
                    "timing": timing,
                    "requester_id": int(requester_id or 0),
                    "requester_name": requester_name[:100],
                    "entry_id": str(entry_id),
                    "lane": str(lane),
                    "insertion_reason": str(insertion_reason)[:200],
                    "source": str(source),
                    "requester_key": str(requester_key or requester_id or ""),
                    "created_at": time.time(),
                }
            )
            del entries[:-200]
            self._write(guilds)

    def consume(self, guild_id: int, track_key: str) -> dict[str, Any] | None:
        if not track_key:
            return None
        with self._lock:
            guilds = self._read()
            entries = guilds.get(str(int(guild_id)), [])
            selected = None
            retained = []
            for entry in entries:
                if selected is None and str(entry.get("track_key") or "") == track_key:
                    selected = entry
                    continue
                retained.append(entry)
            if retained:
                guilds[str(int(guild_id))] = retained
            else:
                guilds.pop(str(int(guild_id)), None)
            self._write(guilds)
            return dict(selected) if isinstance(selected, dict) else None

    def pending_keys(self, guild_id: int) -> set[str]:
        with self._lock:
            entries = self._read().get(str(int(guild_id)), [])
            return {
                str(entry.get("track_key") or "")
                for entry in entries
                if str(entry.get("track_key") or "")
            }

    def entries(self, guild_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(entry)
                for entry in self._read().get(str(int(guild_id)), [])
                if isinstance(entry, dict)
            ]

    def count(self, guild_id: int) -> int:
        with self._lock:
            return len(self._read().get(str(int(guild_id)), []))

    def replace_entries(
        self,
        guild_id: int,
        entries: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            guilds = self._read()
            cleaned = [
                dict(entry)
                for entry in entries
                if isinstance(entry, dict)
                and str(entry.get("track_key") or "")
            ][-200:]
            if cleaned:
                guilds[str(int(guild_id))] = cleaned
            else:
                guilds.pop(str(int(guild_id)), None)
            self._write(guilds)

    def clear_all(self) -> None:
        with self._lock:
            self._write({})

    def _write(self, guilds: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                {"schema": 1, "guilds": guilds},
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)
