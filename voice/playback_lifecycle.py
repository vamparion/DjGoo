from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from voice.operational_log import log_event


LIFECYCLE_STATES = {
    "searching",
    "queued",
    "loading",
    "playing",
    "ended",
    "skipped",
    "failed",
}
TERMINAL_STATES = {"ended", "skipped", "failed"}
ALLOWED_TRANSITIONS = {
    # Player events can legitimately overtake command acknowledgements. A stop,
    # replacement, or very short track may end while its operation still reads
    # searching/loading, so both states accept the externally verified ending.
    "searching": {"queued", "loading", "ended", "failed"},
    "queued": {"loading", "playing", "skipped", "failed"},
    "loading": {"queued", "playing", "ended", "skipped", "failed"},
    "playing": {"ended", "skipped", "failed"},
    "ended": set(),
    "skipped": set(),
    "failed": set(),
}


def operation_id(value: str | None = None) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return str(uuid.uuid4())


class PlaybackLifecycleStore:
    """Durable command and track lifecycle journal used by every control surface."""

    def __init__(self, path: Path, *, history_limit: int = 500) -> None:
        self.path = path
        self.history_limit = max(50, int(history_limit))
        self._lock = threading.RLock()

    def begin(
        self,
        guild_id: int,
        *,
        intent: str,
        source: str,
        query: str = "",
        command_id: str | None = None,
    ) -> str:
        identifier = operation_id(command_id)
        self.transition(
            guild_id,
            identifier,
            "searching",
            intent=intent,
            source=source,
            query=query,
            reason="Command accepted",
        )
        return identifier

    def transition(
        self,
        guild_id: int,
        identifier: str,
        state: str,
        *,
        reason: str = "",
        track: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        normalized = str(state).strip().lower()
        if normalized not in LIFECYCLE_STATES:
            raise ValueError(f"Unsupported playback lifecycle state: {state}")
        now = time.time()
        with self._lock:
            payload = self._read()
            guilds = payload.setdefault("guilds", {})
            guild = guilds.setdefault(str(int(guild_id)), {"active": {}, "history": []})
            active = guild.setdefault("active", {})
            history = guild.setdefault("history", [])
            previous = active.get(identifier)
            if isinstance(previous, dict):
                prior_state = str(previous.get("state") or "")
                if prior_state in TERMINAL_STATES and normalized != prior_state:
                    return dict(previous)
                allowed = ALLOWED_TRANSITIONS.get(prior_state, set())
                if normalized != prior_state and normalized not in allowed:
                    raise ValueError(
                        f"Invalid playback lifecycle transition: {prior_state} -> {normalized}"
                    )
                record = dict(previous)
            else:
                if normalized != "searching":
                    record = {
                        "operation_id": identifier,
                        "created_at": now,
                        "state": "searching",
                    }
                else:
                    record = {"operation_id": identifier, "created_at": now}
            record.update({key: value for key, value in fields.items() if value is not None})
            record.update(
                {
                    "operation_id": identifier,
                    "guild_id": int(guild_id),
                    "state": normalized,
                    "reason": str(reason)[:500],
                    "updated_at": now,
                }
            )
            if track is not None:
                record["track"] = dict(track)
            event = {
                "operation_id": identifier,
                "state": normalized,
                "reason": str(reason)[:500],
                "at": now,
            }
            record.setdefault("events", []).append(event)
            record["events"] = record["events"][-20:]
            if normalized in TERMINAL_STATES:
                active.pop(identifier, None)
                history.insert(0, record)
                del history[self.history_limit :]
            else:
                active[identifier] = record
            self._write(payload)
            log_event(
                "playback.lifecycle",
                guild_id=int(guild_id),
                operation_id=identifier,
                intent=str(record.get("intent") or ""),
                state=normalized,
                reason=str(reason)[:500],
                track_key=str(record.get("track_key") or ""),
            )
            return dict(record)

    def latest(self, guild_id: int) -> dict[str, Any] | None:
        with self._lock:
            guild = self._read().get("guilds", {}).get(str(int(guild_id)), {})
            records = [
                item
                for item in [
                    *dict(guild.get("active") or {}).values(),
                    *list(guild.get("history") or []),
                ]
                if isinstance(item, dict)
            ]
            if not records:
                return None
            return dict(max(records, key=lambda item: float(item.get("updated_at") or 0)))

    def failures(self, guild_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            guild = self._read().get("guilds", {}).get(str(int(guild_id)), {})
            return [
                dict(item)
                for item in guild.get("history", [])
                if isinstance(item, dict) and item.get("state") == "failed"
            ][: max(1, int(limit))]

    def active_for_track(self, guild_id: int, track_key: str) -> dict[str, Any] | None:
        with self._lock:
            guild = self._read().get("guilds", {}).get(str(int(guild_id)), {})
            for record in dict(guild.get("active") or {}).values():
                if not isinstance(record, dict):
                    continue
                if str(record.get("track_key") or "") == str(track_key):
                    return dict(record)
        return None

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": 1, "guilds": {}}
        if not isinstance(payload, dict):
            return {"schema": 1, "guilds": {}}
        payload.setdefault("schema", 1)
        payload.setdefault("guilds", {})
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
