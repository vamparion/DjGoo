from __future__ import annotations

import asyncio
from pathlib import Path

from voice.connection_manager import pair_from_invite as _pair_from_invite
from voice.lan_discovery import discover_gateway_urls
from voice.pairing_bundle import PairingEndpoint, PairingInvite


async def invite_with_discovered_lan_routes(
    invite: PairingInvite,
) -> tuple[PairingInvite, list[str]]:
    """Prepend routes proven by recipient-led LAN discovery to an invite."""

    direct = [
        endpoint
        for endpoint in invite.ordered_endpoints()
        if endpoint.transport == "direct"
    ]
    templates: dict[str, PairingEndpoint] = {}
    for endpoint in direct:
        templates.setdefault(endpoint.security.lower(), endpoint)

    fingerprints = list(templates)
    results = await asyncio.gather(
        *(
            discover_gateway_urls(fingerprint)
            for fingerprint in fingerprints
        ),
        return_exceptions=True,
    )
    discovered: list[PairingEndpoint] = []
    discovered_urls: list[str] = []
    for fingerprint, result in zip(fingerprints, results):
        if isinstance(result, BaseException):
            continue
        template = templates[fingerprint]
        for url in result:
            normalized = str(url).strip().rstrip("/")
            if not normalized or normalized in discovered_urls:
                continue
            discovered_urls.append(normalized)
            discovered.append(
                PairingEndpoint(
                    transport="direct",
                    endpoint=normalized,
                    security=template.security,
                    code=template.code,
                )
            )

    endpoints: list[PairingEndpoint] = []
    seen: set[tuple[str, str, str]] = set()
    for endpoint in [*discovered, *invite.endpoints]:
        key = (
            endpoint.transport.strip().lower(),
            endpoint.endpoint.strip().rstrip("/"),
            endpoint.security.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(endpoint)

    augmented = PairingInvite(
        code=invite.code,
        endpoints=tuple(endpoints),
        expires_at=invite.expires_at,
        host_name=invite.host_name,
        guild_name=invite.guild_name,
        protocol=invite.protocol,
    )
    augmented.validate()
    return augmented, discovered_urls


def _invite_for_transports(
    invite: PairingInvite,
    transports: set[str],
) -> PairingInvite | None:
    endpoints = tuple(
        endpoint
        for endpoint in invite.endpoints
        if endpoint.transport.strip().lower() in transports
    )
    if not endpoints:
        return None
    selected = PairingInvite(
        code=invite.code,
        endpoints=endpoints,
        expires_at=invite.expires_at,
        host_name=invite.host_name,
        guild_name=invite.guild_name,
        protocol=invite.protocol,
    )
    selected.validate()
    return selected


async def pair_from_invite_with_discovery(
    invite: PairingInvite,
    *,
    device_name: str,
    credential_path: Path,
):
    """Use outbound encrypted pairing first; LAN discovery is only a backup."""

    internet = _invite_for_transports(invite, {"discord", "relay"})
    internet_error: Exception | None = None
    if internet is not None:
        try:
            return await _pair_from_invite(
                internet,
                device_name=device_name,
                credential_path=credential_path,
            )
        except Exception as exc:
            internet_error = exc

    augmented, discovered = await invite_with_discovered_lan_routes(invite)
    direct = _invite_for_transports(augmented, {"direct"})
    if direct is not None:
        try:
            return await _pair_from_invite(
                direct,
                device_name=device_name,
                credential_path=credential_path,
            )
        except Exception as direct_error:
            internet_text = (
                f"outbound route failed: {internet_error}"
                if internet_error is not None
                else "the invite contained no outbound encrypted route"
            )
            discovery_text = (
                f"LAN discovery found {len(discovered)} pinned Host route(s)"
                if discovered
                else "LAN discovery found no pinned Host response"
            )
            raise RuntimeError(
                f"DjGoo could not complete secure pairing ({internet_text}; "
                f"direct backup failed: {direct_error}). {discovery_text}."
            ) from direct_error

    if internet_error is not None:
        raise RuntimeError(
            "DjGoo could not complete secure pairing through its outbound "
            f"encrypted route: {internet_error}."
        ) from internet_error
    raise RuntimeError(
        "DjGoo pairing invite contained no usable outbound or direct route."
    )
