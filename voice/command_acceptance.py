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
    actor_role: str = "member"


AuthorizeCallback = Callable[[DeviceIdentity, str], Awaitable[AuthorizationResult]]
StateCallback = Callable[[DeviceIdentity], Awaitable[dict[str, Any]]]
SignalCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

WEB_INTENT_CAPABILITY = {
    "play": "playback.request",
    "play_now": "playback.request",
    "queue_request": "playback.request",
    "play_playlist": "playback.request",
    "queue": "queue.read",
    "skip": "playback.vote_skip",
    "pause": "playback.control",
    "resume": "playback.control",
    "stop": "playback.control",
    "volume": "playback.control",
    "radio": "radio.control",
    "start_radio": "radio.control",
    "stop_radio": "radio.control",
    "station_like_current": "radio.feedback",
    "station_more_like_current": "radio.feedback",
    "station_less_like_current": "radio.feedback",
    "station_ban_current": "radio.feedback",
    "toggle_pause": "playback.control",
    "volume_up": "playback.control",
    "volume_down": "playback.control",
    "mini_queue_remove": "playback.control",
    "mini_queue_remove_many": "playback.control",
    "mini_queue_reorder": "playback.control",
    "mini_queue_shuffle": "playback.control",
    "mini_queue_shuffle_requests": "playback.control",
    "mini_queue_clear": "playback.control",
    "mini_queue_undo": "playback.control",
    "mini_playlist_add_current": "playback.request",
    "remote_playlist_action": "playback.control",
    "remote_station_action": "radio.control",
    "remote_settings": "playback.control",
    "remote_player_role": "playback.control",
}


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
        state_provider: StateCallback | None = None,
        signal_provider: SignalCallback | None = None,
    ) -> None:
        self.pairing_store = pairing_store
        self.queue_path = queue_path
        self.authorize = authorize
        self.state_provider = state_provider
        self.signal_provider = signal_provider
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
            "protocol": 2,
            "device_id": identity.device_id,
            "device_token": token,
            "discord_user_id": str(identity.user_id),
            "guild_id": str(identity.guild_id),
            "device_type": identity.device_type,
            "capabilities": list(identity.capabilities),
        }

    async def status(self, token: str) -> dict[str, Any]:
        identity = await asyncio.to_thread(self.pairing_store.authenticate, token)
        if identity is None:
            raise CommandRejected(401, "Unknown or revoked device")
        return {
            "service": "djgoo-link",
            "status": "connected",
            "protocol": 2,
            "device_id": identity.device_id,
            "device_name": identity.device_name,
            "discord_user_id": str(identity.user_id),
            "guild_id": str(identity.guild_id),
            "last_seen_at": identity.last_seen_at,
            "end_to_end_encrypted": True,
            "device_type": identity.device_type,
            "capabilities": list(identity.capabilities),
        }

    async def remote_state(self, token: str) -> dict[str, Any]:
        identity = await asyncio.to_thread(self.pairing_store.authenticate, token)
        if identity is None:
            raise CommandRejected(401, "Unknown or revoked device")
        if identity.device_type != "web" or "state.read" not in identity.capabilities:
            raise CommandRejected(403, "This device cannot read remote player state")
        authorization = await self.authorize(identity, "state.read")
        if not authorization.allowed:
            raise CommandRejected(403, authorization.reason or "Remote state is not authorized")
        if self.state_provider is None:
            raise CommandRejected(503, "Remote player state is unavailable")
        return await self.state_provider(identity)

    async def webrtc_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.signal_provider is None:
            raise CommandRejected(503, "Direct browser connection is unavailable")
        return await self.signal_provider(payload)

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
            raise CommandRejected(403, "Device is not paired to that server")
        if identity.device_type == "web":
            required = WEB_INTENT_CAPABILITY.get(intent)
            if required is None or required not in identity.capabilities:
                raise CommandRejected(403, "That action is not enabled for this web device")

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
            "source": "web_remote" if identity.device_type == "web" else "voice_remote",
            "created_at": created_at,
            "command_id": command_id,
            "device_id": identity.device_id,
            "user_id": identity.user_id,
            "guild_id": identity.guild_id,
            "voice_channel_id": authorization.voice_channel_id,
            "actor_role": authorization.actor_role,
            "intent": intent,
            "query": str(payload.get("query") or "")[:500],
            "playlist": str(payload.get("playlist") or "")[:200],
            "value": payload.get("value"),
            "confidence": confidence,
            "raw": str(payload.get("raw") or "")[:1000],
            "payload": payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        }
        with self._queue_lock:
            append_queue_item(self.queue_path, item)
        return {"accepted": True, "duplicate": False, "command_id": command_id}
