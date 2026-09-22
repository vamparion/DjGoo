from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = 2
ACK_MAX_AGE_SECONDS = 24 * 60 * 60
HISTORY_LIMIT = 200


def new_command_id() -> str:
    return str(uuid.uuid4())


def mini_player_command(
    intent: str,
    *,
    query: str = "",
    playlist: str = "",
    value: Any = 0,
    payload: Mapping[str, Any] | None = None,
    command_id: str | None = None,
) -> dict[str, Any]:
    identifier = command_id or new_command_id()
    return {
        "type": "command",
        "source": "mini_player",
        "actor_role": "host",
        "protocol": PROTOCOL_VERSION,
        "created_at": time.time(),
        "command_id": identifier,
        "intent": str(intent).strip(),
        "query": str(query).strip(),
        "playlist": str(playlist).strip(),
        "value": value,
        "payload": dict(payload or {}),
        "confidence": 1.0,
        "raw": f"mini:{intent}",
    }


def result_failed(result: Any) -> bool:
    if isinstance(result, Mapping):
        status = str(result.get("status") or "").lower()
        return status in {"error", "failed", "rejected"}
    text = str(result or "").strip().lower()
    return any(
        marker in text
        for marker in (
            "failed",
            "missing",
            "unavailable",
            "nothing playing",
            "queue empty",
            "no audio context",
            "no voice context",
            "not loaded",
            "not find",
            "unknown command",
            "invalid queue",
        )
    )


class CommandReceiptStore:
    """Durable per-command acknowledgments shared by Redbot and the Mini Player."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(
        self,
        command_id: str,
        *,
        result: Any,
        intent: str,
        success: bool | None = None,
    ) -> Path | None:
        try:
            identifier = str(uuid.UUID(str(command_id)))
        except (ValueError, AttributeError):
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{identifier}.json"
        temporary = destination.with_suffix(".json.tmp")
        resolved_success = not result_failed(result) if success is None else bool(success)
        payload = {
            "protocol": PROTOCOL_VERSION,
            "command_id": identifier,
            "intent": str(intent),
            "success": resolved_success,
            "status": "completed" if resolved_success else "failed",
            "completed_at": time.time(),
            "result": result,
        }
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        self.prune()
        return destination

    def read(self, command_id: str, *, consume: bool = False) -> dict[str, Any] | None:
        try:
            identifier = str(uuid.UUID(str(command_id)))
        except (ValueError, AttributeError):
            return None
        path = self.directory / f"{identifier}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if consume:
            path.unlink(missing_ok=True)
        return payload if isinstance(payload, dict) else None

    def prune(self, *, max_age_seconds: float = ACK_MAX_AGE_SECONDS) -> None:
        if not self.directory.exists():
            return
        cutoff = time.time() - float(max_age_seconds)
        for path in self.directory.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue


class MiniPlayerHistory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read()

    def add(self, track: Mapping[str, Any], *, mode: str, station: str = "") -> None:
        item = {
            "id": str(track.get("id") or uuid.uuid4()),
            "title": str(track.get("title") or "Unknown track"),
            "artist": str(track.get("artist") or ""),
            "uri": str(track.get("uri") or ""),
            "artwork_url": str(track.get("artwork_url") or ""),
            "duration_seconds": int(track.get("duration_seconds") or 0),
            "mode": str(mode),
            "station": str(station),
            "played_at": time.time(),
        }
        with self._lock:
            entries = self._read()
            if entries:
                previous = entries[0]
                if (
                    previous.get("uri") == item["uri"]
                    and previous.get("title") == item["title"]
                    and time.time() - float(previous.get("played_at") or 0) < 20
                ):
                    return
            entries.insert(0, item)
            self._write(entries[:HISTORY_LIMIT])

    def _read(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        return [dict(item) for item in entries if isinstance(item, dict)]

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"schema": 1, "entries": entries},
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
