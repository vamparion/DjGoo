from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from voice.pairing_bundle import PairingEndpoint, PairingInvite
from voice.relay_transport import RelayCredential, RelayTransport
from voice.remote_transport import RemoteCredential, RemoteGatewayTransport
from voice.secure_store import load_protected_json, save_protected_json


RecipientCredential = RemoteCredential | RelayCredential
RecipientTransport = RemoteGatewayTransport | RelayTransport
CONNECTION_SCHEMA = 2


def _credential_from_data(data: dict[str, Any]) -> RecipientCredential:
    transport = str(data.get("transport") or "direct").strip().lower()
    if transport == "relay":
        return RelayCredential(
            transport="relay",
            relay_url=str(data["relay_url"]),
            room_id=str(data["room_id"]),
            host_encryption_public_key=str(data["host_encryption_public_key"]),
            host_encryption_fingerprint_sha256=str(
                data["host_encryption_fingerprint_sha256"]
            ),
            device_id=str(data["device_id"]),
            device_token=str(data["device_token"]),
            discord_user_id=str(data["discord_user_id"]),
            guild_id=str(data["guild_id"]),
        )
    return RemoteCredential(
        gateway_url=str(data["gateway_url"]),
        tls_fingerprint_sha256=str(data["tls_fingerprint_sha256"]),
        device_id=str(data["device_id"]),
        device_token=str(data["device_token"]),
        discord_user_id=str(data["discord_user_id"]),
        guild_id=str(data["guild_id"]),
        transport="direct",
    )


def _credential_for_endpoint(
    endpoint: PairingEndpoint,
    authenticated: RecipientCredential,
) -> RecipientCredential:
    if endpoint.transport == "direct":
        return RemoteCredential(
            gateway_url=endpoint.endpoint.rstrip("/"),
            tls_fingerprint_sha256=endpoint.security,
            device_id=authenticated.device_id,
            device_token=authenticated.device_token,
            discord_user_id=authenticated.discord_user_id,
            guild_id=authenticated.guild_id,
            transport="direct",
        )
    if endpoint.transport == "relay":
        return RelayCredential(
            transport="relay",
            relay_url=endpoint.endpoint.rstrip("/"),
            room_id=endpoint.room_id,
            host_encryption_public_key=endpoint.host_public_key,
            host_encryption_fingerprint_sha256=endpoint.security,
            device_id=authenticated.device_id,
            device_token=authenticated.device_token,
            discord_user_id=authenticated.discord_user_id,
            guild_id=authenticated.guild_id,
        )
    raise ValueError(f"Unsupported DjGoo recipient transport: {endpoint.transport}")


def _save_connection(
    path: Path,
    credentials: list[RecipientCredential],
    *,
    preferred_transport: str,
) -> None:
    save_protected_json(
        path,
        {
            "schema": CONNECTION_SCHEMA,
            "preferred_transport": preferred_transport,
            "credentials": [asdict(credential) for credential in credentials],
        },
    )


async def _probed_pairing_endpoints(
    invite: PairingInvite,
) -> tuple[PairingEndpoint, ...]:
    """Place reachable direct routes first without delaying relay fallback."""

    endpoints = list(invite.ordered_endpoints())
    direct = [item for item in endpoints if item.transport == "direct"]
    relay = [item for item in endpoints if item.transport == "relay"]
    if not direct:
        return tuple(relay)

    results = await asyncio.gather(
        *(
            RemoteGatewayTransport.probe(item.endpoint, item.security)
            for item in direct
        ),
        return_exceptions=True,
    )
    reachable: list[PairingEndpoint] = []
    unreachable: list[PairingEndpoint] = []
    for endpoint, result in zip(direct, results):
        (reachable if result is True else unreachable).append(endpoint)

    # A relay is more useful than spending several seconds on every route that
    # already failed a pinned health probe. Keep one unresponsive direct route as
    # a final safety attempt for unusual proxies, but do it after relay.
    return tuple([*reachable, *relay, *unreachable[:1]])


async def pair_from_invite(
    invite: PairingInvite,
    *,
    device_name: str,
    credential_path: Path,
) -> tuple[RecipientCredential, str]:
    invite.validate()
    errors: list[str] = []
    authenticated: RecipientCredential | None = None
    selected_transport = ""

    endpoints = await _probed_pairing_endpoints(invite)
    for endpoint in endpoints:
        pairing_code = endpoint.pairing_code(invite.code)
        try:
            if endpoint.transport == "direct":
                authenticated = await RemoteGatewayTransport.pair(
                    endpoint.endpoint,
                    pairing_code,
                    endpoint.security,
                    device_name=device_name,
                )
            elif endpoint.transport == "relay":
                authenticated = await RelayTransport.pair(
                    endpoint.endpoint,
                    endpoint.room_id,
                    pairing_code,
                    endpoint.host_public_key,
                    endpoint.security,
                    device_name=device_name,
                )
            else:
                continue
        except Exception as exc:
            errors.append(f"{endpoint.transport}: {type(exc).__name__}: {exc}")
            continue
        selected_transport = endpoint.transport
        break

    if authenticated is None:
        detail = "; ".join(errors[-4:]) if errors else "no supported connection method"
        raise RuntimeError(f"DjGoo could not complete secure pairing ({detail})")

    credentials = [
        _credential_for_endpoint(endpoint, authenticated)
        for endpoint in invite.ordered_endpoints()
    ]
    _save_connection(
        credential_path,
        credentials,
        preferred_transport=selected_transport,
    )
    primary = next(
        (
            credential
            for credential in credentials
            if credential.transport == selected_transport
        ),
        credentials[0],
    )
    return primary, selected_transport


def load_recipient_credentials(
    path: Path,
) -> tuple[list[RecipientCredential], str]:
    data = load_protected_json(path)
    raw_credentials = data.get("credentials")
    if isinstance(raw_credentials, list):
        credentials = [
            _credential_from_data(item)
            for item in raw_credentials
            if isinstance(item, dict)
        ]
        if not credentials:
            raise ValueError("DjGoo recipient connection contains no usable route")
        preferred = str(
            data.get("preferred_transport") or credentials[0].transport
        ).strip().lower()
        return credentials, preferred

    credential = _credential_from_data(data)
    return [credential], credential.transport


def _ordered_credentials(
    credentials: list[RecipientCredential],
    preferred_transport: str,
) -> list[RecipientCredential]:
    return sorted(
        credentials,
        key=lambda credential: (
            0 if credential.transport == preferred_transport else 1,
            0 if credential.transport == "direct" else 1,
        ),
    )


def load_recipient_credential(path: Path) -> RecipientCredential:
    credentials, preferred = load_recipient_credentials(path)
    return _ordered_credentials(credentials, preferred)[0]


def transport_for_credential(
    credential: RecipientCredential,
) -> RecipientTransport:
    if isinstance(credential, RelayCredential):
        return RelayTransport(credential)
    return RemoteGatewayTransport(credential)


class RecipientFailoverTransport:
    """Use one device identity over every pinned connection route."""

    def __init__(
        self,
        credential_path: Path,
        credentials: list[RecipientCredential],
        preferred_transport: str,
    ) -> None:
        self.credential_path = credential_path
        self.credentials = list(credentials)
        self.preferred_transport = preferred_transport
        self.credential = _ordered_credentials(
            self.credentials,
            self.preferred_transport,
        )[0]

    def _ordered_transports(self) -> list[RecipientTransport]:
        return [
            transport_for_credential(credential)
            for credential in _ordered_credentials(
                self.credentials,
                self.preferred_transport,
            )
        ]

    def _record_preferred(self, transport_name: str) -> None:
        normalized = transport_name.strip().lower()
        if normalized == self.preferred_transport:
            return
        self.preferred_transport = normalized
        self.credential = _ordered_credentials(
            self.credentials,
            self.preferred_transport,
        )[0]
        _save_connection(
            self.credential_path,
            self.credentials,
            preferred_transport=self.preferred_transport,
        )

    async def send_async(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        payload.setdefault("command_id", str(uuid.uuid4()))
        errors: list[str] = []
        for transport in self._ordered_transports():
            name = transport.credential.transport
            try:
                result = await transport.send_async(payload)
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            self._record_preferred(name)
            return {**result, "transport": name}
        raise RuntimeError(
            "Every secure DjGoo Link route failed ("
            + "; ".join(errors[-4:])
            + ")"
        )

    async def status_async(self) -> dict[str, Any]:
        errors: list[str] = []
        configured = [credential.transport for credential in self.credentials]
        for transport in self._ordered_transports():
            name = transport.credential.transport
            try:
                result = await transport.status_async()
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            self._record_preferred(name)
            return {
                **result,
                "transport": name,
                "configured_transports": configured,
            }
        raise RuntimeError(
            "Every secure DjGoo Link route failed ("
            + "; ".join(errors[-4:])
            + ")"
        )

    def send(self, item: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send_async(item))

    def status(self) -> dict[str, Any]:
        return asyncio.run(self.status_async())


def load_recipient_transport(path: Path) -> RecipientFailoverTransport:
    credentials, preferred = load_recipient_credentials(path)
    return RecipientFailoverTransport(path, credentials, preferred)


def recipient_status(path: Path) -> dict[str, Any]:
    credentials, preferred = load_recipient_credentials(path)
    transport = RecipientFailoverTransport(path, credentials, preferred)
    result = transport.status()
    credential = transport.credential
    return {
        "transport": str(result.get("transport") or credential.transport),
        "configured_transports": result.get(
            "configured_transports",
            [item.transport for item in credentials],
        ),
        "device_id": credential.device_id,
        "discord_user_id": credential.discord_user_id,
        "guild_id": credential.guild_id,
        **result,
    }
