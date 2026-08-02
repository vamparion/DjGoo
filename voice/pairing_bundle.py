from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


PAIRING_SCHEME = "djgoo"
PAIRING_HOST = "pair"
PAIRING_PROTOCOL = 2
MAX_INVITE_BYTES = 16_384


def _normalized_code(value: str) -> str:
    return "".join(
        character
        for character in value.upper()
        if character.isalnum()
    )


def _valid_discord_webhook(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    allowed = {
        "discord.com",
        "www.discord.com",
        "ptb.discord.com",
        "canary.discord.com",
        "discordapp.com",
        "www.discordapp.com",
    }
    if parsed.scheme.lower() != "https" or host not in allowed:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) not in {4, 5} or not parts or parts[0] != "api":
        return False
    offset = 2 if len(parts) > 1 and parts[1].startswith("v") and parts[1][1:].isdigit() else 1
    return bool(
        len(parts) == offset + 3
        and parts[offset] == "webhooks"
        and parts[offset + 1].isdigit()
        and parts[offset + 2]
    )


@dataclass(frozen=True)
class PairingEndpoint:
    transport: str
    endpoint: str
    security: str
    code: str = ""
    room_id: str = ""
    host_public_key: str = ""

    def validate(self, *, fallback_code: str = "") -> None:
        mode = self.transport.strip().lower()
        endpoint = self.endpoint.strip()
        security = "".join(
            character
            for character in self.security.lower()
            if character in "0123456789abcdef"
        )
        effective_code = _normalized_code(self.code or fallback_code)
        if len(effective_code) != 8:
            raise ValueError(
                "Every DjGoo pairing route requires its own eight-character code"
            )
        if mode == "direct":
            if not endpoint.lower().startswith("https://"):
                raise ValueError("Direct pairing endpoints must use https://")
            if len(security) != 64:
                raise ValueError(
                    "Direct pairing requires a SHA-256 TLS fingerprint"
                )
            return
        if mode == "discord":
            if not _valid_discord_webhook(endpoint):
                raise ValueError(
                    "Discord pairing requires a valid HTTPS Discord webhook"
                )
            if len(security) != 64:
                raise ValueError(
                    "Discord pairing requires a SHA-256 Host key fingerprint"
                )
            if not self.room_id.strip() or not self.host_public_key.strip():
                raise ValueError(
                    "Discord pairing requires a room ID and Host public key"
                )
            return
        if mode == "relay":
            if not endpoint.lower().startswith("wss://"):
                raise ValueError("Relay pairing endpoints must use wss://")
            if len(security) != 64:
                raise ValueError(
                    "Relay pairing requires a SHA-256 Host key fingerprint"
                )
            if not self.room_id.strip() or not self.host_public_key.strip():
                raise ValueError(
                    "Relay pairing requires a room ID and Host public key"
                )
            return
        raise ValueError(
            f"Unsupported DjGoo pairing transport: {self.transport}"
        )

    def pairing_code(self, fallback_code: str = "") -> str:
        return _normalized_code(self.code or fallback_code)


@dataclass(frozen=True)
class PairingInvite:
    code: str
    endpoints: tuple[PairingEndpoint, ...]
    expires_at: float
    host_name: str = "DjGoo Host"
    guild_name: str = ""
    protocol: int = PAIRING_PROTOCOL

    def validate(
        self,
        *,
        now: float | None = None,
        allow_expired: bool = False,
    ) -> None:
        if int(self.protocol) != PAIRING_PROTOCOL:
            raise ValueError(
                f"Unsupported DjGoo pairing protocol: {self.protocol}"
            )
        fallback_code = _normalized_code(self.code)
        if fallback_code and len(fallback_code) != 8:
            raise ValueError(
                "DjGoo pairing codes must contain eight characters"
            )
        if not self.endpoints:
            raise ValueError(
                "DjGoo pairing invite contains no connection endpoint"
            )
        for endpoint in self.endpoints:
            endpoint.validate(fallback_code=fallback_code)
        current = time.time() if now is None else float(now)
        if not allow_expired and float(self.expires_at) <= current:
            raise ValueError("This DjGoo pairing invite has expired")

    def ordered_endpoints(self) -> tuple[PairingEndpoint, ...]:
        priority = {"direct": 0, "discord": 1, "relay": 2}
        return tuple(
            sorted(
                self.endpoints,
                key=lambda item: priority.get(item.transport, 99),
            )
        )

    def to_uri(self) -> str:
        self.validate(allow_expired=True)
        payload = {
            "protocol": self.protocol,
            "code": self.code,
            "expires_at": self.expires_at,
            "host_name": self.host_name,
            "guild_name": self.guild_name,
            "endpoints": [
                asdict(endpoint)
                for endpoint in self.endpoints
            ],
        }
        encoded = _encode_payload(payload)
        return f"{PAIRING_SCHEME}://{PAIRING_HOST}?d={encoded}"

    def safety_number(self) -> str:
        digest = hashlib.sha256(
            self.to_uri().encode("utf-8")
        ).digest()
        value = int.from_bytes(digest[:4], "big") % 1_000_000
        return f"{value:06d}"


def build_invite(
    *,
    code: str = "",
    expires_at: float,
    direct_url: str = "",
    direct_fingerprint: str = "",
    direct_code: str = "",
    relay_url: str = "",
    relay_fingerprint: str = "",
    relay_code: str = "",
    room_id: str = "",
    host_public_key: str = "",
    host_name: str = "DjGoo Host",
    guild_name: str = "",
) -> PairingInvite:
    endpoints: list[PairingEndpoint] = []
    if direct_url.strip():
        endpoints.append(
            PairingEndpoint(
                transport="direct",
                endpoint=direct_url.strip(),
                security=direct_fingerprint.strip(),
                code=(direct_code or code).strip(),
            )
        )
    if relay_url.strip():
        endpoints.append(
            PairingEndpoint(
                transport="relay",
                endpoint=relay_url.strip(),
                security=relay_fingerprint.strip(),
                code=(relay_code or code).strip(),
                room_id=room_id.strip(),
                host_public_key=host_public_key.strip(),
            )
        )
    invite = PairingInvite(
        code=code.strip() if not (direct_code or relay_code) else "",
        endpoints=tuple(endpoints),
        expires_at=float(expires_at),
        host_name=" ".join(host_name.split())[:80] or "DjGoo Host",
        guild_name=" ".join(guild_name.split())[:100],
    )
    invite.validate(allow_expired=True)
    return invite


def parse_invite(
    value: str,
    *,
    now: float | None = None,
    allow_expired: bool = False,
) -> PairingInvite:
    text = value.strip()
    if not text:
        raise ValueError("Paste the DjGoo pairing invite from Discord")
    if len(text.encode("utf-8")) > MAX_INVITE_BYTES:
        raise ValueError("DjGoo pairing invite is too large")

    if text.startswith("{"):
        payload = json.loads(text)
    else:
        parsed = urlparse(text)
        if (
            parsed.scheme.lower() != PAIRING_SCHEME
            or parsed.netloc.lower() != PAIRING_HOST
        ):
            raise ValueError("This is not a DjGoo pairing invite")
        encoded = (parse_qs(parsed.query).get("d") or [""])[0]
        payload = _decode_payload(encoded)

    if not isinstance(payload, dict):
        raise ValueError("DjGoo pairing invite payload is invalid")
    raw_endpoints = payload.get("endpoints")
    if not isinstance(raw_endpoints, list):
        raise ValueError("DjGoo pairing invite endpoints are invalid")
    endpoints = tuple(
        PairingEndpoint(
            transport=str(item.get("transport") or ""),
            endpoint=str(item.get("endpoint") or ""),
            security=str(item.get("security") or ""),
            code=str(item.get("code") or ""),
            room_id=str(item.get("room_id") or ""),
            host_public_key=str(item.get("host_public_key") or ""),
        )
        for item in raw_endpoints
        if isinstance(item, dict)
    )
    invite = PairingInvite(
        protocol=int(payload.get("protocol") or 0),
        code=str(payload.get("code") or ""),
        endpoints=endpoints,
        expires_at=float(payload.get("expires_at") or 0),
        host_name=str(payload.get("host_name") or "DjGoo Host"),
        guild_name=str(payload.get("guild_name") or ""),
    )
    invite.validate(
        now=now,
        allow_expired=allow_expired,
    )
    return invite


def _encode_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(encoded: str) -> dict[str, Any]:
    if not encoded:
        raise ValueError("DjGoo pairing invite payload is missing")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(encoded + padding)
        payload = json.loads(raw.decode("utf-8"))
    except (
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            "DjGoo pairing invite payload is corrupted"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("DjGoo pairing invite payload is invalid")
    return payload
