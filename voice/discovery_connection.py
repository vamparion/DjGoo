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


async def pair_from_invite_with_discovery(
    invite: PairingInvite,
    *,
    device_name: str,
    credential_path: Path,
):
    """Discover the reachable Host first, then use normal pinned-route failover."""

    augmented, discovered = await invite_with_discovered_lan_routes(invite)
    try:
        return await _pair_from_invite(
            augmented,
            device_name=device_name,
            credential_path=credential_path,
        )
    except Exception as exc:
        available = sorted(
            {
                endpoint.transport
                for endpoint in invite.endpoints
                if endpoint.transport in {"discord", "relay"}
            }
        )
        discovery_text = (
            f"LAN discovery found {len(discovered)} pinned Host route(s)"
            if discovered
            else "LAN discovery found no pinned Host response"
        )
        fallback_text = (
            "internet fallback offered: " + ", ".join(available)
            if available
            else "the invite contained no internet fallback"
        )
        raise RuntimeError(
            f"{exc}. {discovery_text}; {fallback_text}."
        ) from exc
