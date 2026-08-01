from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import web

from voice.command_acceptance import (
    AuthenticatedCommandProcessor,
    AuthorizationResult,
    AuthorizeCallback,
    CommandRejected,
)
from voice.pairing_store import PairingStore
from voice.tls_identity import TlsIdentity


MAX_BODY_BYTES = 16_384


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
        self.processor = AuthenticatedCommandProcessor(pairing_store, remote_queue_path, authorize)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def fingerprint(self) -> str:
        return self.tls_identity.fingerprint_sha256

    def application(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY_BYTES)
        app.router.add_get("/v1/health", self.health)
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
                "service": "djgoo-voice-gateway",
                "status": "ok",
                "protocol": 1,
                "tls_fingerprint_sha256": self.fingerprint,
            }
        )

    async def _json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json(loads=json.loads)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise web.HTTPBadRequest(text="Invalid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="JSON object required")
        if any(key in payload for key in ("audio", "pcm", "samples", "microphone")):
            raise web.HTTPBadRequest(text="Raw microphone audio is not accepted")
        return payload

    @staticmethod
    def _raise_http(error: CommandRejected) -> None:
        exception_type = {
            400: web.HTTPBadRequest,
            401: web.HTTPUnauthorized,
            403: web.HTTPForbidden,
            429: web.HTTPTooManyRequests,
        }.get(error.status, web.HTTPBadRequest)
        raise exception_type(text=error.message)

    async def pair(self, request: web.Request) -> web.Response:
        payload = await self._json(request)
        try:
            result = await self.processor.redeem_pairing(
                str(payload.get("code") or ""),
                str(payload.get("device_name") or "DjGoo Voice Remote"),
            )
        except CommandRejected as error:
            self._raise_http(error)
            raise AssertionError("unreachable")
        result["tls_fingerprint_sha256"] = self.fingerprint
        return web.json_response(result, status=201)

    @staticmethod
    def _bearer_token(request: web.Request) -> str:
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise web.HTTPUnauthorized(text="Bearer device token required")
        return token.strip()

    async def command(self, request: web.Request) -> web.Response:
        token = self._bearer_token(request)
        payload = await self._json(request)
        try:
            result = await self.processor.accept(token, payload)
        except CommandRejected as error:
            self._raise_http(error)
            raise AssertionError("unreachable")
        return web.json_response(result, status=200 if result.get("duplicate") else 202)


__all__ = [
    "AuthorizationResult",
    "AuthorizeCallback",
    "VoiceCommandGateway",
]
