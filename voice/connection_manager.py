from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from voice.pairing_bundle import PairingInvite
from voice.relay_transport import RelayCredential, RelayTransport
from voice.remote_transport import RemoteCredential, RemoteGatewayTransport
from voice.secure_store import load_protected_json, save_protected_json


RecipientCredential = RemoteCredential | RelayCredential
RecipientTransport = RemoteGatewayTransport | RelayTransport


async def pair_from_invite(
    invite: PairingInvite,
    *,
    device_name: str,
    credential_path: Path,
) -> tuple[RecipientCredential, str]:
    invite.validate()
    errors: list[str] = []
    for endpoint in invite.ordered_endpoints():
        try:
            if endpoint.transport == "direct":
                credential: RecipientCredential = await RemoteGatewayTransport.pair(
                    endpoint.endpoint,
                    invite.code,
                    endpoint.security,
                    device_name=device_name,
                )
            elif endpoint.transport == "relay":
                credential = await RelayTransport.pair(
                    endpoint.endpoint,
                    endpoint.room_id,
                    invite.code,
                    endpoint.host_public_key,
                    endpoint.security,
                    device_name=device_name,
                )
            else:
                continue
        except Exception as exc:
            errors.append(f"{endpoint.transport}: {type(exc).__name__}: {exc}")
            continue
        save_protected_json(credential_path, asdict(credential))
        return credential, endpoint.transport
    detail = "; ".join(errors[-3:]) if errors else "no supported connection method"
    raise RuntimeError(f"DjGoo could not complete secure pairing ({detail})")


def load_recipient_credential(path: Path) -> RecipientCredential:
    data = load_protected_json(path)
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


def transport_for_credential(credential: RecipientCredential) -> RecipientTransport:
    if isinstance(credential, RelayCredential):
        return RelayTransport(credential)
    return RemoteGatewayTransport(credential)


def load_recipient_transport(path: Path) -> RecipientTransport:
    return transport_for_credential(load_recipient_credential(path))


def recipient_status(path: Path) -> dict[str, Any]:
    credential = load_recipient_credential(path)
    transport = transport_for_credential(credential)
    result = transport.status()
    return {
        "transport": credential.transport,
        "device_id": credential.device_id,
        "discord_user_id": credential.discord_user_id,
        "guild_id": credential.guild_id,
        **result,
    }
