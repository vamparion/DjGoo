from __future__ import annotations

import asyncio
import math
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from voice.command_queue import append_queue_item
from voice.pairing_store import DeviceIdentity, PairingStore


MAX_COMMANDS_PER_WINDOW = 12
RATE_WINDOW_SECONDS = 10.0
MAX_COMMAND_AGE_SECONDS = 300.0
MAX_CLOCK_SKEW_SECONDS = 60.0


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    reason: str = ""
    voice_channel_id: int | None = None


AuthorizeCallback = Callable[[DeviceIdentity, str], Awaitable[AuthorizationResult]]


class CommandRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = int(status)
        self.message = message


class DeviceRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, device_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[device_id]
            while events and now - events[0] > RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= MAX_COMMANDS_PER_WINDOW:
                return False
            events.append(now)
            return True


class AuthenticatedCommandProcessor:
    def __init__(
        self,
        pairing_store: PairingStore,
        queue_path: Path,
        authorize: AuthorizeCallback,
    ) -> None:
        self.pairing_store = pairing_store
        self.queue_path = queue_path
        self.authorize = authorize
        self._queue_lock = threading.Lock()
        self._limiter = DeviceRateLimiter()

    async def redeem_pairing(self, code: str, device_name: str) -> dict[str, Any]:
        redeemed = await asyncio.to_thread(
            self.pairing_store.redeem_pairing_code,
            code,
            device_name,
        )
        if redeemed is None:
            raise CommandRejected(401, "Pairing code is invalid or expired")
        identity, token = redeemed
        return {
            "protocol": 1,
            "device_id": identity.device_id,
            "device_token": token,
            "discord_user_id": str(identity.user_id),
            "guild_id": str(identity.guild_id),
        }

    async def accept(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        identity = await asyncio.to_thread(self.pairing_store.authenticate, token)
        if identity is None:
            raise CommandRejected(401, "Unknown or revoked device")
        if not self._limiter.allow(identity.device_id):
            raise CommandRejected(429, "Voice command rate limit exceeded")

        command_id = str(payload.get("command_id") or "")
        try:
            uuid.UUID(command_id)
        except (ValueError, AttributeError) as exc:
            raise CommandRejected(400, "A valid command UUID is required") from exc

        intent = str(payload.get("intent") or "").strip()
        if not intent or len(intent) > 64:
            raise CommandRejected(400, "A valid intent is required")
        if str(payload.get("guild_id") or identity.guild_id) != str(identity.guild_id):
            raise CommandRejected(403, "Device is not paired to that guild")

        now = time.time()
        try:
            created_at = float(payload.get("created_at") or now)
            confidence = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError) as exc:
            raise CommandRejected(400, "Invalid command timestamp or confidence") from exc
        if not math.isfinite(created_at) or not math.isfinite(confidence):
            raise CommandRejected(400, "Invalid command timestamp or confidence")
        if created_at < now - MAX_COMMAND_AGE_SECONDS or created_at > now + MAX_CLOCK_SKEW_SECONDS:
            raise CommandRejected(400, "Command timestamp is stale or too far in the future")
        confidence = min(1.0, max(0.0, confidence))

        authorization = await self.authorize(identity, intent)
        if not authorization.allowed:
            raise CommandRejected(403, authorization.reason or "Command is not authorized")

        claimed = await asyncio.to_thread(
            self.pairing_store.claim_command,
            command_id,
            identity.device_id,
        )
        if not claimed:
            return {"accepted": True, "duplicate": True, "command_id": command_id}

        item = {
            "type": "command",
            "source": "voice_remote",
            "created_at": created_at,
            "command_id": command_id,
            "device_id": identity.device_id,
            "user_id": identity.user_id,
            "guild_id": identity.guild_id,
            "voice_channel_id": authorization.voice_channel_id,
            "intent": intent,
            "query": str(payload.get("query") or "")[:500],
            "playlist": str(payload.get("playlist") or "")[:200],
            "value": payload.get("value"),
            "confidence": confidence,
            "raw": str(payload.get("raw") or "")[:1000],
        }
        with self._queue_lock:
            append_queue_item(self.queue_path, item)
        return {"accepted": True, "duplicate": False, "command_id": command_id}
