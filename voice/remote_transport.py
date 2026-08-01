from __future__ import annotations

import asyncio
import json
import socket
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

import aiohttp


@dataclass(frozen=True)
class RemoteCredential:
    gateway_url: str
    tls_fingerprint_sha256: str
    device_id: str
    device_token: str
    discord_user_id: str
    guild_id: str
    transport: str = "direct"

    def redacted(self) -> dict[str, str]:
        payload = asdict(self)
        payload["device_token"] = "<redacted>"
        return payload


class CommandTransport(Protocol):
    def send(self, item: dict[str, Any]) -> dict[str, Any]: ...


def normalize_fingerprint(value: str) -> str:
    normalized = "".join(character for character in value.lower() if character in "0123456789abcdef")
    if len(normalized) != 64:
        raise ValueError("TLS fingerprint must contain 64 hexadecimal characters")
    return normalized


def normalize_gateway_url(value: str) -> str:
    url = value.strip().rstrip("/") + "/"
    if not url.lower().startswith("https://"):
        raise ValueError("DjGoo Voice Gateway URLs must use https://")
    return url


class RemoteGatewayTransport:
    def __init__(self, credential: RemoteCredential, timeout_seconds: float = 12.0) -> None:
        if credential.transport != "direct":
            raise ValueError("Direct gateway credential has the wrong transport type")
        self.credential = credential
        self.timeout_seconds = float(timeout_seconds)
        self._fingerprint = aiohttp.Fingerprint(bytes.fromhex(normalize_fingerprint(credential.tls_fingerprint_sha256)))

    @classmethod
    async def pair(
        cls,
        gateway_url: str,
        pairing_code: str,
        tls_fingerprint_sha256: str,
        device_name: str | None = None,
    ) -> RemoteCredential:
        normalized_url = normalize_gateway_url(gateway_url)
        fingerprint = normalize_fingerprint(tls_fingerprint_sha256)
        ssl_fingerprint = aiohttp.Fingerprint(bytes.fromhex(fingerprint))
        timeout = aiohttp.ClientTimeout(total=15)
        payload = {
            "code": pairing_code,
            "device_name": device_name or socket.gethostname() or "DjGoo Voice Remote",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                urljoin(normalized_url, "v1/pair"),
                json=payload,
                ssl=ssl_fingerprint,
            ) as response:
                text = await response.text()
                if response.status not in {200, 201}:
                    raise RuntimeError(f"Pairing failed ({response.status}): {text[:300]}")
                data = json.loads(text)
        returned_fingerprint = normalize_fingerprint(str(data.get("tls_fingerprint_sha256") or fingerprint))
        if returned_fingerprint != fingerprint:
            raise RuntimeError("Gateway fingerprint changed during pairing")
        return RemoteCredential(
            gateway_url=normalized_url.rstrip("/"),
            tls_fingerprint_sha256=fingerprint,
            device_id=str(data["device_id"]),
            device_token=str(data["device_token"]),
            discord_user_id=str(data["discord_user_id"]),
            guild_id=str(data["guild_id"]),
        )

    async def send_async(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        payload.setdefault("command_id", str(uuid.uuid4()))
        payload["guild_id"] = self.credential.guild_id
        headers = {"Authorization": f"Bearer {self.credential.device_token}"}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                urljoin(normalize_gateway_url(self.credential.gateway_url), "v1/command"),
                json=payload,
                headers=headers,
                ssl=self._fingerprint,
            ) as response:
                text = await response.text()
                if response.status not in {200, 202}:
                    raise RuntimeError(f"Command rejected ({response.status}): {text[:300]}")
                data = json.loads(text)
                return data if isinstance(data, dict) else {"accepted": False}

    def send(self, item: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send_async(item))


def save_credential(path: Path, credential: Any) -> None:
    if not is_dataclass(credential):
        raise TypeError("Voice Remote credential must be a dataclass")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(credential), indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_credential(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Remote credential file is invalid")
    transport = str(data.get("transport") or "direct")
    if transport == "relay":
        from voice.relay_transport import RelayCredential

        return RelayCredential(
            transport="relay",
            relay_url=str(data["relay_url"]),
            room_id=str(data["room_id"]),
            host_encryption_public_key=str(data["host_encryption_public_key"]),
            host_encryption_fingerprint_sha256=str(data["host_encryption_fingerprint_sha256"]),
            device_id=str(data["device_id"]),
            device_token=str(data["device_token"]),
            discord_user_id=str(data["discord_user_id"]),
            guild_id=str(data["guild_id"]),
        )
    if transport != "direct":
        raise ValueError(f"Unsupported Voice Remote transport: {transport}")
    return RemoteCredential(
        gateway_url=normalize_gateway_url(str(data["gateway_url"])).rstrip("/"),
        tls_fingerprint_sha256=normalize_fingerprint(str(data["tls_fingerprint_sha256"])),
        device_id=str(data["device_id"]),
        device_token=str(data["device_token"]),
        discord_user_id=str(data["discord_user_id"]),
        guild_id=str(data["guild_id"]),
        transport="direct",
    )


def transport_for_credential(credential: Any) -> CommandTransport:
    if getattr(credential, "transport", "direct") == "relay":
        from voice.relay_transport import RelayTransport

        return RelayTransport(credential)
    return RemoteGatewayTransport(credential)
