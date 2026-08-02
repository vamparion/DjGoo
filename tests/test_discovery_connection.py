from __future__ import annotations

import asyncio
import time

import voice.discovery_connection as discovery_connection
from voice.pairing_bundle import PairingEndpoint, PairingInvite


def test_discovered_route_precedes_guessed_adapter_address(monkeypatch) -> None:
    fingerprint = "c" * 64

    async def discover(*args, **kwargs):
        return ["https://192.168.8.50:47632"]

    monkeypatch.setattr(
        discovery_connection,
        "discover_gateway_urls",
        discover,
    )
    invite = PairingInvite(
        code="",
        endpoints=(
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security=fingerprint,
                code="ABCD1234",
            ),
        ),
        expires_at=time.time() + 60,
    )

    augmented, discovered = asyncio.run(
        discovery_connection.invite_with_discovered_lan_routes(invite)
    )

    assert discovered == ["https://192.168.8.50:47632"]
    assert [endpoint.endpoint for endpoint in augmented.endpoints] == [
        "https://192.168.8.50:47632",
        "https://192.168.8.128:47632",
    ]
    assert augmented.endpoints[0].security == fingerprint
    assert augmented.endpoints[0].code == "ABCD1234"


def test_discovery_deduplicates_an_existing_invite_route(monkeypatch) -> None:
    fingerprint = "d" * 64

    async def discover(*args, **kwargs):
        return ["https://192.168.8.128:47632"]

    monkeypatch.setattr(
        discovery_connection,
        "discover_gateway_urls",
        discover,
    )
    invite = PairingInvite(
        code="",
        endpoints=(
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security=fingerprint,
                code="ABCD1234",
            ),
        ),
        expires_at=time.time() + 60,
    )

    augmented, _ = asyncio.run(
        discovery_connection.invite_with_discovered_lan_routes(invite)
    )

    assert len(augmented.endpoints) == 1
