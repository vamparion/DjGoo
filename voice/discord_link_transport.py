from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

from voice.relay_crypto import (
    decrypt_response,
    encrypt_request,
    public_key_fingerprint,
)


REQUEST_PREFIX = "DJGOO-LINK-1:"
RESPONSE_PREFIX = "DJGOO-LINK-1-RESPONSE:"
WEBHOOK_PATH_RE = re.compile(r"^/api(?:/v\d+)?/webhooks/(\d+)/([^/]+)$")
DISCORD_HOSTS = {
    "discord.com",
    "www.discord.com",
    "canary.discord.com",
    "ptb.discord.com",
    "discordapp.com",
    "www.discordapp.com",
}
MAX_CONTENT_LENGTH = 1_950


@dataclass(frozen=True)
class DiscordLinkCredential:
    transport: str
    webhook_url: str
    webhook_id: str
    host_encryption_public_key: str
    host_encryption_fingerprint_sha256: str
    device_id: str
    device_token: str
    discord_user_id: str
    guild_id: str


def normalize_webhook_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() != "https" or parsed.hostname not in DISCORD_HOSTS:
        raise ValueError("DjGoo Discord Link requires an official Discord HTTPS webhook")
    match = WEBHOOK_PATH_RE.fullmatch(parsed.path.rstrip("/"))
    if match is None:
        raise ValueError("DjGoo Discord Link webhook URL is invalid")
    webhook_id = match.group(1)
    normalized = urlunparse(
        (
            "https",
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
            "",
        )
    )
    return normalized, webhook_id


def _with_query(url: str, **values: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _encode_envelope(prefix: str, envelope: dict[str, Any]) -> str:
    raw = json.dumps(
        envelope,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    content = prefix + encoded
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError("DjGoo Link encrypted message is too large for Discord")
    return content


def _decode_envelope(prefix: str, content: str) -> dict[str, Any]:
    if not content.startswith(prefix):
        raise ValueError("DjGoo Link response marker is missing")
    encoded = content[len(prefix) :].strip()
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("DjGoo Link encrypted response is corrupted") from exc
    if not isinstance(payload, dict):
        raise ValueError("DjGoo Link encrypted response is invalid")
    return payload


class DiscordLinkTransport:
    def __init__(
        self,
        credential: DiscordLinkCredential,
        *,
        timeout_seconds: float = 18.0,
    ) -> None:
        if credential.transport != "discord":
            raise ValueError("Discord Link transport received the wrong credential type")
        webhook_url, webhook_id = normalize_webhook_url(credential.webhook_url)
        if webhook_id != str(credential.webhook_id):
            raise ValueError("Discord Link webhook identity changed")
        fingerprint = public_key_fingerprint(
            credential.host_encryption_public_key
        )
        if fingerprint != credential.host_encryption_fingerprint_sha256:
            raise ValueError("Discord Link Host identity fingerprint does not match")
        self.credential = DiscordLinkCredential(
            **{
                **credential.__dict__,
                "webhook_url": webhook_url,
                "webhook_id": webhook_id,
            }
        )
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    async def pair(
        cls,
        webhook_url: str,
        pairing_code: str,
        host_public_key: str,
        host_fingerprint: str,
        *,
        device_name: str,
    ) -> DiscordLinkCredential:
        normalized_url, webhook_id = normalize_webhook_url(webhook_url)
        if public_key_fingerprint(host_public_key) != host_fingerprint:
            raise ValueError("Discord Link Host identity fingerprint does not match")
        temporary = DiscordLinkCredential(
            transport="discord",
            webhook_url=normalized_url,
            webhook_id=webhook_id,
            host_encryption_public_key=host_public_key,
            host_encryption_fingerprint_sha256=host_fingerprint,
            device_id="",
            device_token="",
            discord_user_id="",
            guild_id="",
        )
        transport = cls(temporary)
        response = await transport._exchange(
            "pair",
            {
                "code": pairing_code,
                "device_name": device_name,
            },
        )
        return DiscordLinkCredential(
            transport="discord",
            webhook_url=normalized_url,
            webhook_id=webhook_id,
            host_encryption_public_key=host_public_key,
            host_encryption_fingerprint_sha256=host_fingerprint,
            device_id=str(response["device_id"]),
            device_token=str(response["device_token"]),
            discord_user_id=str(response["discord_user_id"]),
            guild_id=str(response["guild_id"]),
        )

    async def _exchange(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        envelope, private_key = encrypt_request(
            self.credential.host_encryption_public_key,
            self.credential.webhook_id,
            request_id,
            action,
            payload,
        )
        content = _encode_envelope(REQUEST_PREFIX, envelope)
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds + 5)
        message_id = ""
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                _with_query(self.credential.webhook_url, wait="true"),
                json={
                    "username": "DjGoo Link",
                    "content": content,
                    "allowed_mentions": {"parse": []},
                },
            ) as response:
                text = await response.text()
                if response.status not in {200, 201}:
                    raise RuntimeError(
                        f"Discord Link request failed ({response.status}): {text[:200]}"
                    )
                message = json.loads(text)
                message_id = str(message.get("id") or "")
            if not message_id:
                raise RuntimeError("Discord Link did not return a message identifier")

            message_url = (
                f"{self.credential.webhook_url}/messages/{message_id}"
            )
            deadline = time.monotonic() + self.timeout_seconds
            try:
                while time.monotonic() < deadline:
                    async with session.get(message_url) as response:
                        if response.status == 200:
                            message = await response.json()
                            response_content = str(message.get("content") or "")
                            if response_content.startswith(RESPONSE_PREFIX):
                                response_envelope = _decode_envelope(
                                    RESPONSE_PREFIX,
                                    response_content,
                                )
                                return decrypt_response(
                                    private_key,
                                    response_envelope,
                                    self.credential.webhook_id,
                                    request_id,
                                )
                        elif response.status == 404:
                            raise RuntimeError(
                                "Discord Link message disappeared before the Host answered"
                            )
                    await asyncio.sleep(0.4)
            finally:
                try:
                    async with session.delete(message_url):
                        pass
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
        raise TimeoutError("DjGoo Host did not answer through Discord Link")

    async def send_async(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        payload.setdefault("command_id", str(uuid.uuid4()))
        payload["device_id"] = self.credential.device_id
        payload["device_token"] = self.credential.device_token
        payload["guild_id"] = self.credential.guild_id
        return await self._exchange("command", payload)

    async def status_async(self) -> dict[str, Any]:
        return await self._exchange(
            "status",
            {
                "device_id": self.credential.device_id,
                "device_token": self.credential.device_token,
                "guild_id": self.credential.guild_id,
            },
        )

    def send(self, item: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send_async(item))

    def status(self) -> dict[str, Any]:
        return asyncio.run(self.status_async())
