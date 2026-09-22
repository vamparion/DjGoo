from __future__ import annotations

import asyncio
import base64
import json
import socket
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from voice.relay_crypto import decrypt_response, encrypt_request
from voice.relay_transport import (
    normalize_key_fingerprint,
    verify_host_public_key,
)


REQUEST_PREFIX = "DJGOO-LINK-1:"
RESPONSE_PREFIX = "DJGOO-LINK-1-RESPONSE:"
RESPONSE_ATTACHMENT_PREFIX = "DJGOO-LINK-1-ATTACHMENT:"
ERROR_PREFIX = "DJGOO-LINK-1-ERROR:"
MAX_DISCORD_CONTENT = 1950
POLL_INTERVAL_SECONDS = 0.35


def normalize_discord_webhook_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    allowed_hosts = {
        "discord.com",
        "www.discord.com",
        "ptb.discord.com",
        "canary.discord.com",
        "discordapp.com",
        "www.discordapp.com",
    }
    if parsed.scheme.lower() != "https" or host not in allowed_hosts:
        raise ValueError("DjGoo Discord relay requires an HTTPS Discord webhook URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) not in {4, 5}:
        raise ValueError("DjGoo Discord relay webhook URL is invalid")
    if parts[0] != "api":
        raise ValueError("DjGoo Discord relay webhook URL is invalid")
    offset = 1
    if parts[1].startswith("v") and parts[1][1:].isdigit():
        offset = 2
    if len(parts) != offset + 3 or parts[offset] != "webhooks":
        raise ValueError("DjGoo Discord relay webhook URL is invalid")
    webhook_id = parts[offset + 1]
    token = parts[offset + 2]
    if not webhook_id.isdigit() or not token:
        raise ValueError("DjGoo Discord relay webhook URL is invalid")
    path = "/" + "/".join(parts)
    return urlunsplit(("https", parsed.netloc, path, "", ""))


def discord_webhook_id(value: str) -> int:
    normalized = normalize_discord_webhook_url(value)
    parts = [part for part in urlsplit(normalized).path.split("/") if part]
    index = parts.index("webhooks")
    return int(parts[index + 1])


def _encode_envelope(envelope: dict[str, Any]) -> str:
    raw = json.dumps(
        envelope,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_envelope(value: str) -> dict[str, Any]:
    encoded = value.strip()
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        )
    except (
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        base64.binascii.Error,
    ) as exc:
        raise ValueError("Discord relay envelope is corrupted") from exc
    if not isinstance(payload, dict):
        raise ValueError("Discord relay envelope is invalid")
    return payload


def encode_discord_request(envelope: dict[str, Any]) -> str:
    content = REQUEST_PREFIX + _encode_envelope(envelope)
    if len(content) > MAX_DISCORD_CONTENT:
        raise ValueError("Encrypted DjGoo request is too large for Discord relay")
    return content


def decode_discord_request(content: str) -> dict[str, Any]:
    if not content.startswith(REQUEST_PREFIX):
        raise ValueError("Message is not a DjGoo Discord relay request")
    return _decode_envelope(content[len(REQUEST_PREFIX) :])


def encode_discord_response(envelope: dict[str, Any]) -> str:
    content = RESPONSE_PREFIX + _encode_envelope(envelope)
    if len(content) > MAX_DISCORD_CONTENT:
        raise ValueError("Encrypted DjGoo response is too large for Discord relay")
    return content


def decode_discord_response(content: str) -> dict[str, Any]:
    if not content.startswith(RESPONSE_PREFIX):
        raise ValueError("Message is not a DjGoo Discord relay response")
    return _decode_envelope(content[len(RESPONSE_PREFIX) :])


def discord_message_url(webhook_url: str, message_id: str | int) -> str:
    return (
        normalize_discord_webhook_url(webhook_url).rstrip("/")
        + f"/messages/{str(message_id).strip()}"
    )


async def _response_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    text = await response.text()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


async def _rate_limit_delay(response: aiohttp.ClientResponse) -> float:
    payload = await _response_json(response)
    try:
        return max(0.1, min(5.0, float(payload.get("retry_after") or 1.0)))
    except (TypeError, ValueError):
        return 1.0


async def update_discord_message(
    webhook_url: str,
    message_id: str | int,
    content: str,
) -> None:
    if len(content) > MAX_DISCORD_CONTENT:
        raise ValueError("Discord relay response content is too large")
    url = discord_message_url(webhook_url, message_id)
    timeout = aiohttp.ClientTimeout(total=15, sock_connect=8, sock_read=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(4):
            async with session.patch(
                url,
                json={
                    "content": content,
                    "allowed_mentions": {"parse": []},
                },
            ) as response:
                if response.status == 429:
                    await asyncio.sleep(await _rate_limit_delay(response))
                    continue
                if response.status != 200:
                    detail = (await response.text())[:300]
                    raise RuntimeError(
                        "Discord relay could not publish Host response "
                        f"({response.status}): {detail}"
                    )
                return
    raise RuntimeError("Discord relay response remained rate limited")


async def publish_discord_response(
    webhook_url: str,
    message_id: str | int,
    envelope: dict[str, Any],
) -> None:
    encoded = RESPONSE_PREFIX + _encode_envelope(envelope)
    if len(encoded) <= MAX_DISCORD_CONTENT:
        await update_discord_message(webhook_url, message_id, encoded)
        return
    url = discord_message_url(webhook_url, message_id)
    marker = RESPONSE_ATTACHMENT_PREFIX + str(envelope.get("request_id") or "")
    timeout = aiohttp.ClientTimeout(total=20, sock_connect=8, sock_read=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(5):
            form = aiohttp.FormData()
            form.add_field(
                "payload_json",
                json.dumps({
                    "content": marker,
                    "attachments": [{"id": 0, "filename": "djgoo-response.txt"}],
                    "allowed_mentions": {"parse": []},
                }),
                content_type="application/json",
            )
            form.add_field(
                "files[0]",
                encoded.encode("ascii"),
                filename="djgoo-response.txt",
                content_type="text/plain",
            )
            async with session.patch(url, data=form) as response:
                if response.status == 429:
                    await asyncio.sleep(await _rate_limit_delay(response))
                    continue
                if response.status != 200:
                    detail = (await response.text())[:300]
                    raise RuntimeError(f"Discord relay could not publish Host attachment ({response.status}): {detail}")
                return
    raise RuntimeError("Discord relay attachment remained rate limited")


async def delete_discord_message_after(
    webhook_url: str,
    message_id: str | int,
    *,
    delay_seconds: float = 60.0,
) -> None:
    await asyncio.sleep(max(0.0, delay_seconds))
    url = discord_message_url(webhook_url, message_id)
    timeout = aiohttp.ClientTimeout(total=10, sock_connect=6, sock_read=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.delete(url):
                pass
    except Exception:
        pass


@dataclass(frozen=True)
class DiscordRelayCredential:
    transport: str
    webhook_url: str
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
        payload["webhook_url"] = "<redacted>"
        return payload


class DiscordRelayTransport:
    def __init__(
        self,
        credential: DiscordRelayCredential,
        timeout_seconds: float = 25.0,
    ) -> None:
        if credential.transport != "discord":
            raise ValueError("Discord relay credential has the wrong transport type")
        self.credential = credential
        self.timeout_seconds = float(timeout_seconds)
        self._webhook_url = normalize_discord_webhook_url(
            credential.webhook_url
        )
        verify_host_public_key(
            credential.host_encryption_public_key,
            credential.host_encryption_fingerprint_sha256,
        )

    @classmethod
    async def pair(
        cls,
        webhook_url: str,
        room_id: str,
        pairing_code: str,
        host_encryption_public_key: str,
        host_encryption_fingerprint_sha256: str,
        device_name: str | None = None,
    ) -> DiscordRelayCredential:
        verify_host_public_key(
            host_encryption_public_key,
            host_encryption_fingerprint_sha256,
        )
        result = await cls._round_trip(
            normalize_discord_webhook_url(webhook_url),
            room_id,
            host_encryption_public_key,
            {
                "action": "pair",
                "payload": {
                    "code": pairing_code,
                    "device_name": (
                        device_name
                        or socket.gethostname()
                        or "DjGoo Voice Remote"
                    ),
                },
            },
            timeout_seconds=25.0,
        )
        return DiscordRelayCredential(
            transport="discord",
            webhook_url=normalize_discord_webhook_url(webhook_url),
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
            self._webhook_url,
            self.credential.room_id,
            self.credential.host_encryption_public_key,
            {"action": "command", "payload": payload},
            timeout_seconds=self.timeout_seconds,
        )

    async def status_async(self) -> dict[str, Any]:
        return await self._round_trip(
            self._webhook_url,
            self.credential.room_id,
            self.credential.host_encryption_public_key,
            {
                "action": "status",
                "payload": {"device_token": self.credential.device_token},
            },
            timeout_seconds=self.timeout_seconds,
        )

    def send(self, item: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send_async(item))

    def status(self) -> dict[str, Any]:
        return asyncio.run(self.status_async())

    @staticmethod
    async def _round_trip(
        webhook_url: str,
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
        content = encode_discord_request(envelope)
        timeout = aiohttp.ClientTimeout(
            total=max(10.0, timeout_seconds + 5.0),
            sock_connect=10,
            sock_read=max(10.0, timeout_seconds),
        )
        message_id = ""
        deadline = time.monotonic() + timeout_seconds

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(4):
                async with session.post(
                    webhook_url,
                    params={"wait": "true"},
                    json={
                        "content": content,
                        "allowed_mentions": {"parse": []},
                    },
                ) as response:
                    if response.status == 429:
                        await asyncio.sleep(await _rate_limit_delay(response))
                        continue
                    payload = await _response_json(response)
                    if response.status not in {200, 201}:
                        raise RuntimeError(
                            "Discord relay could not create request "
                            f"({response.status})"
                        )
                    message_id = str(payload.get("id") or "")
                    if not message_id:
                        raise RuntimeError(
                            "Discord relay did not return a message ID"
                        )
                    break
            if not message_id:
                raise RuntimeError("Discord relay remained rate limited")

            message_url = discord_message_url(webhook_url, message_id)
            try:
                while time.monotonic() < deadline:
                    async with session.get(message_url) as response:
                        if response.status == 429:
                            await asyncio.sleep(
                                await _rate_limit_delay(response)
                            )
                            continue
                        payload = await _response_json(response)
                        if response.status != 200:
                            raise RuntimeError(
                                "Discord relay response check failed "
                                f"({response.status})"
                            )
                    returned_content = str(payload.get("content") or "")
                    if returned_content.startswith(RESPONSE_PREFIX):
                        response_envelope = decode_discord_response(
                            returned_content
                        )
                        decoded = decrypt_response(
                            request_key,
                            response_envelope,
                        )
                        if not bool(decoded.get("ok")):
                            raise RuntimeError(
                                "Host rejected request "
                                f"({decoded.get('status', 500)}): "
                                f"{decoded.get('error', 'unknown error')}"
                            )
                        result = decoded.get("result")
                        if not isinstance(result, dict):
                            raise RuntimeError(
                                "Host response did not contain a result object"
                            )
                        return result
                    if returned_content.startswith(ERROR_PREFIX):
                        raise RuntimeError(
                            returned_content[len(ERROR_PREFIX) :][:300]
                            or "Discord relay Host error"
                        )
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                raise asyncio.TimeoutError(
                    "Discord relay timed out waiting for the Host"
                )
            finally:
                try:
                    async with session.delete(message_url):
                        pass
                except Exception:
                    pass
