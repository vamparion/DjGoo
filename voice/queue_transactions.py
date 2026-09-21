from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping


class QueueTransactionStore:
    """Durable audit and undo metadata for mutations of the real player queue."""

    def __init__(self, path: Path, *, limit: int = 100) -> None:
        self.path = path
        self.limit = max(10, int(limit))
        self._lock = threading.RLock()

    def record(
        self,
        guild_id: int,
        *,
        action: str,
        before: Iterable[Mapping[str, Any]],
        after: Iterable[Mapping[str, Any]],
        source: str,
        reason: str,
        operation_id: str = "",
    ) -> str:
        transaction_id = str(uuid.uuid4())
        entry = {
            "transaction_id": transaction_id,
            "operation_id": str(operation_id),
            "guild_id": int(guild_id),
            "action": str(action),
            "source": str(source),
            "reason": str(reason)[:500],
            "created_at": time.time(),
            "before": [dict(item) for item in before],
            "after": [dict(item) for item in after],
        }
        with self._lock:
            payload = self._read()
            entries = payload.setdefault("guilds", {}).setdefault(str(int(guild_id)), [])
            entries.insert(0, entry)
            del entries[self.limit :]
            self._write(payload)
        return transaction_id

    def latest(self, guild_id: int) -> dict[str, Any] | None:
        with self._lock:
            entries = self._read().get("guilds", {}).get(str(int(guild_id)), [])
            return dict(entries[0]) if entries and isinstance(entries[0], dict) else None

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": 1, "guilds": {}}
        return payload if isinstance(payload, dict) else {"schema": 1, "guilds": {}}

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
