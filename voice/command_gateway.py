from __future__ import annotations

import asyncio
import json
import math
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from aiohttp import web

from voice.command_queue import append_queue_item
from voice.pairing_store import DeviceIdentity, PairingStore
from voice.tls_identity import TlsIdentity


MAX_BODY_BYTES = 16_384
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


class VoiceCommandGateway:
    def __init__(
        self,
        pairing_store: PairingStore,
        remote_queue_path: Path,
        authorize: AuthorizeCallback,
        tls_identity: TlsIdentity,
        *,
        host: str = "127.0.0.1",
        port: int = 47632,
    ) -> None:
        self.pairing_store = pairing_store
        self.remote_queue_path = remote_queue_path
        self.authorize = authorize
        self.tls_identity = tls_identity
        self.host = host
        self.port = int(port)
        self._queue_lock = threading.Lock()
        self._limiter = DeviceRateLimiter()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def fingerprint(self) -> str:
        return self.tls_identity.fingerprint_sha256

    def application(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY_BYTES)
        app.router.add_get("/v1/health", self.health)
        app.router.add_get("/v1/device", self.device)
        app.router.add_post("/v1/pair", self.pair)
        app.router.add_post("/v1/command", self.command)
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self.application(), access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host=self.host,
            port=self.port,
            ssl_context=self.tls_identity.server_context(),
            shutdown_timeout=5.0,
        )
        await self._site.start()

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "service": "djgoo-link",
                "status": "ok",
                "protocol": 2,
                "tls_fingerprint_sha256": self.fingerprint,
            }
        )

    async def device(self, request: web.Request) -> web.Response:
        token = self._bearer_token(request)
        identity = await asyncio.to_thread(self.pairing_store.authenticate, token)
        if identity is None:
            raise web.HTTPUnauthorized(text="Unknown or revoked DjGoo device")
        return web.json_response(
            {
                "service": "djgoo-link",
                "status": "connected",
                "protocol": 2,
                "device_id": identity.device_id,
                "device_name": identity.device_name,
                "discord_user_id": str(identity.user_id),
                "guild_id": str(identity.guild_id),
                "last_seen_at": identity.last_seen_at,
                "certificate_pinned": True,
            }
        )

    async def _json(self, request: web.Request) -> dict[str, object]:
        try:
            payload = await request.json(loads=json.loads)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise web.HTTPBadRequest(text="Invalid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="JSON object required")
        if any(key in payload for key in ("audio", "pcm", "samples", "microphone")):
            raise web.HTTPBadRequest(text="Raw microphone audio is not accepted")
        return payload

    async def pair(self, request: web.Request) -> web.Response:
        payload = await self._json(request)
        code = str(payload.get("code") or "")
        device_name = str(payload.get("device_name") or "DjGoo Voice Remote")
        redeemed = await asyncio.to_thread(
            self.pairing_store.redeem_pairing_code,
            code,
            device_name,
        )
        if redeemed is None:
            raise web.HTTPUnauthorized(text="Pairing code is invalid or expired")
        identity, token = redeemed
        return web.json_response(
            {
                "protocol": 2,
                "device_id": identity.device_id,
                "device_token": token,
                "discord_user_id": str(identity.user_id),
                "guild_id": str(identity.guild_id),
                "tls_fingerprint_sha256": self.fingerprint,
            },
            status=201,
        )

    def _bearer_token(self, request: web.Request) -> str:
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise web.HTTPUnauthorized(text="Bearer device token required")
        return token.strip()

    async def command(self, request: web.Request) -> web.Response:
        token = self._bearer_token(request)
        identity = await asyncio.to_thread(self.pairing_store.authenticate, token)
        if identity is None:
            raise web.HTTPUnauthorized(text="Unknown or revoked device")
        if not self._limiter.allow(identity.device_id):
            raise web.HTTPTooManyRequests(text="Voice command rate limit exceeded")

        payload = await self._json(request)
        command_id = str(payload.get("command_id") or "")
        try:
            uuid.UUID(command_id)
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest(text="A valid command UUID is required")

        intent = str(payload.get("intent") or "").strip()
        if not intent or len(intent) > 64:
            raise web.HTTPBadRequest(text="A valid intent is required")
        if str(payload.get("guild_id") or identity.guild_id) != str(identity.guild_id):
            raise web.HTTPForbidden(text="Device is not paired to that server")

        now = time.time()
        try:
            created_at = float(payload.get("created_at") or now)
            confidence = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Invalid command timestamp or confidence")
        if not math.isfinite(created_at) or not math.isfinite(confidence):
            raise web.HTTPBadRequest(text="Invalid command timestamp or confidence")
        if created_at < now - MAX_COMMAND_AGE_SECONDS or created_at > now + MAX_CLOCK_SKEW_SECONDS:
            raise web.HTTPBadRequest(text="Command timestamp is stale or too far in the future")
        confidence = min(1.0, max(0.0, confidence))

        authorization = await self.authorize(identity, intent)
        if not authorization.allowed:
            raise web.HTTPForbidden(text=authorization.reason or "Command is not authorized")

        claimed = await asyncio.to_thread(
            self.pairing_store.claim_command,
            command_id,
            identity.device_id,
        )
        if not claimed:
            return web.json_response(
                {"accepted": True, "duplicate": True, "command_id": command_id}
            )

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
            append_queue_item(self.remote_queue_path, item)
        return web.json_response(
            {"accepted": True, "duplicate": False, "command_id": command_id},
            status=202,
        )
