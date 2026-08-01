from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any
from urllib.parse import urljoin

import aiohttp

from voice.command_acceptance import AuthenticatedCommandProcessor, CommandRejected
from voice.operational_log import log_event
from voice.relay_crypto import (
    RelayHostIdentity,
    decrypt_request,
    encrypt_response,
)


class RelayHostClient:
    def __init__(
        self,
        relay_url: str,
        identity: RelayHostIdentity,
        processor: AuthenticatedCommandProcessor,
    ) -> None:
        normalized = relay_url.strip().rstrip("/") + "/"
        if not normalized.lower().startswith("wss://"):
            raise ValueError("Public DjGoo relay URLs must use wss://")
        self.relay_url = normalized
        self.identity = identity
        self.processor = processor
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def room_id(self) -> str:
        return self.identity.room_id

    @property
    def encryption_public_key(self) -> str:
        return self.identity.encryption_public_b64

    @property
    def encryption_fingerprint(self) -> str:
        return self.identity.encryption_fingerprint_sha256

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self.run(), name="djgoo-relay-host")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        delay = 1.0
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=75)
        while not self._stop.is_set():
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    await self._run_session(session)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(
                    "voice.relay.host.disconnected",
                    error=type(exc).__name__,
                    detail=str(exc),
                    retry_seconds=round(delay, 1),
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(30.0, delay * 2.0)

    async def _run_session(self, session: aiohttp.ClientSession) -> None:
        endpoint = urljoin(self.relay_url, "v1/host")
        async with session.ws_connect(endpoint, heartbeat=25, max_msg_size=64 * 1024, compress=0) as websocket:
            hello = self.identity.sign_host_hello(int(time.time()), secrets.token_urlsafe(18))
            await websocket.send_json(hello)
            ready = await websocket.receive_json(timeout=15)
            if not isinstance(ready, dict) or ready.get("type") != "host_ready":
                raise RuntimeError(f"Relay did not accept Host identity: {ready!r}")
            if str(ready.get("room_id") or "") != self.room_id:
                raise RuntimeError("Relay acknowledged the wrong Host room")
            log_event(
                "voice.relay.host.ready",
                relay_url=self.relay_url,
                room_id=self.room_id,
                encryption_fingerprint=self.encryption_fingerprint,
            )

            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(message.data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict) or payload.get("type") != "relay_request":
                        continue
                    route_id = str(payload.get("route_id") or "")
                    envelope = payload.get("envelope")
                    if not route_id or not isinstance(envelope, dict):
                        continue
                    response = await self._handle_envelope(envelope)
                    await websocket.send_json(
                        {"type": "relay_response", "route_id": route_id, "envelope": response}
                    )
                elif message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break

    async def _handle_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        room_id = str(envelope.get("room_id") or "")
        request_id = str(envelope.get("request_id") or "")
        if room_id != self.room_id:
            raise ValueError("Relay request targeted the wrong Host room")
        plaintext, client_public_key = decrypt_request(
            self.identity.encryption_private_key,
            envelope,
        )
        action = str(plaintext.get("action") or "")
        payload = plaintext.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        try:
            if action == "pair":
                result = await self.processor.redeem_pairing(
                    str(payload.get("code") or ""),
                    str(payload.get("device_name") or "DjGoo Voice Remote"),
                )
            elif action == "command":
                result = await self.processor.accept(
                    str(payload.get("device_token") or ""),
                    payload,
                )
            else:
                raise CommandRejected(400, "Unknown relay action")
            response_plaintext = {"ok": True, "status": 200, "result": result}
        except CommandRejected as error:
            response_plaintext = {
                "ok": False,
                "status": error.status,
                "error": error.message,
            }
        except Exception as exc:
            log_event(
                "voice.relay.host.request_failed",
                request_id=request_id,
                action=action,
                error=type(exc).__name__,
                detail=str(exc),
            )
            response_plaintext = {
                "ok": False,
                "status": 500,
                "error": "Host could not process the encrypted request",
            }
        return encrypt_response(
            client_public_key,
            self.room_id,
            request_id,
            response_plaintext,
        )
