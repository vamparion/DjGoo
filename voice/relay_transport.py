from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

import aiohttp

from voice.relay_crypto import (
    decrypt_response,
    encrypt_request,
)


@dataclass(frozen=True)
class RelayCredential:
    transport: str
    relay_url: str
    room_id: str
    host_encryption_public_key: str
    host_encryption_fingerprint_sha256: str
    device_id: str
    device_token: str
    discord_user_id: str
    guild_id: str

    def redacted(self) -> dict[str, str]:
        payload = asdict(self)
        payload["device_token"] = "<redacted>"
        return payload


def normalize_relay_url(value: str) -> str:
    normalized = value.strip().rstrip("/") + "/"
    allow_insecure = os.environ.get("DJGOO_RELAY_ALLOW_INSECURE", "").strip() == "1"
    if not normalized.lower().startswith("wss://") and not (
        allow_insecure and normalized.lower().startswith("ws://")
    ):
        raise ValueError("DjGoo Relay URLs must use wss://")
    return normalized


def normalize_key_fingerprint(value: str) -> str:
    normalized = "".join(character for character in value.lower() if character in "0123456789abcdef")
    if len(normalized) != 64:
        raise ValueError("Host encryption fingerprint must contain 64 hexadecimal characters")
    return normalized


def verify_host_public_key(public_key_b64: str, expected_fingerprint: str) -> None:
    import base64

    padding = "=" * ((4 - len(public_key_b64.strip()) % 4) % 4)
    raw = base64.urlsafe_b64decode(public_key_b64.strip() + padding)
    if len(raw) != 32:
        raise ValueError("Host relay encryption public key is invalid")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != normalize_key_fingerprint(expected_fingerprint):
        raise ValueError("Host relay encryption key does not match its fingerprint")


class RelayTransport:
    def __init__(self, credential: RelayCredential, timeout_seconds: float = 20.0) -> None:
        if credential.transport != "relay":
            raise ValueError("Relay credential has the wrong transport type")
        self.credential = credential
        self.timeout_seconds = float(timeout_seconds)
        verify_host_public_key(
            credential.host_encryption_public_key,
            credential.host_encryption_fingerprint_sha256,
        )

    @classmethod
    async def pair(
        cls,
        relay_url: str,
        room_id: str,
        pairing_code: str,
        host_encryption_public_key: str,
        host_encryption_fingerprint_sha256: str,
        device_name: str | None = None,
    ) -> RelayCredential:
        verify_host_public_key(host_encryption_public_key, host_encryption_fingerprint_sha256)
        request = {
            "action": "pair",
            "payload": {
                "code": pairing_code,
                "device_name": device_name or socket.gethostname() or "DjGoo Voice Remote",
            },
        }
        result = await cls._round_trip(
            normalize_relay_url(relay_url),
            room_id,
            host_encryption_public_key,
            request,
            timeout_seconds=25.0,
        )
        return RelayCredential(
            transport="relay",
            relay_url=normalize_relay_url(relay_url).rstrip("/"),
            room_id=room_id,
            host_encryption_public_key=host_encryption_public_key,
            host_encryption_fingerprint_sha256=normalize_key_fingerprint(
                host_encryption_fingerprint_sha256
            ),
            device_id=str(result["device_id"]),
            device_token=str(result["device_token"]),
            discord_user_id=str(result["discord_user_id"]),
            guild_id=str(result["guild_id"]),
        )

    async def send_async(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        payload.setdefault("command_id", str(uuid.uuid4()))
        payload["guild_id"] = self.credential.guild_id
        payload["device_token"] = self.credential.device_token
        return await self._round_trip(
            normalize_relay_url(self.credential.relay_url),
            self.credential.room_id,
            self.credential.host_encryption_public_key,
            {"action": "command", "payload": payload},
            timeout_seconds=self.timeout_seconds,
        )

    def send(self, item: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send_async(item))

    @staticmethod
    async def _round_trip(
        relay_url: str,
        room_id: str,
        host_public_key: str,
        plaintext: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        envelope, request_key = encrypt_request(
            host_public_key,
            room_id,
            request_id,
            plaintext,
        )
        endpoint = urljoin(relay_url, f"v1/client/{room_id}")
        timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=12, sock_read=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                endpoint,
                heartbeat=20,
                max_msg_size=64 * 1024,
                compress=0,
            ) as websocket:
                await websocket.send_json({"type": "relay_request", "envelope": envelope})
                message = await websocket.receive(timeout=timeout_seconds)
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError("Relay closed before returning a response")
                response = json.loads(message.data)
                if not isinstance(response, dict):
                    raise RuntimeError("Relay returned an invalid response")
                if response.get("type") == "error":
                    raise RuntimeError(f"Relay error: {response.get('code', 'unknown')}")
                response_envelope = response.get("envelope")
                if not isinstance(response_envelope, dict):
                    raise RuntimeError("Relay response did not contain an encrypted envelope")
                decoded = decrypt_response(request_key, response_envelope)
        if not bool(decoded.get("ok")):
            raise RuntimeError(
                f"Host rejected request ({decoded.get('status', 500)}): {decoded.get('error', 'unknown error')}"
            )
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Host response did not contain a result object")
        return result
