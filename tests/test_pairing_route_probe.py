from __future__ import annotations

import asyncio

from voice import connection_manager
from voice.pairing_bundle import PairingEndpoint, PairingInvite


FINGERPRINT = "a" * 64


def invite() -> PairingInvite:
    return PairingInvite(
        code="",
        expires_at=4_000_000_000,
        endpoints=(
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security=FINGERPRINT,
                code="LOCAL001",
            ),
            PairingEndpoint(
                transport="direct",
                endpoint="https://10.0.0.8:47632",
                security=FINGERPRINT,
                code="LOCAL002",
            ),
            PairingEndpoint(
                transport="relay",
                endpoint="wss://relay.example.test",
                security=FINGERPRINT,
                code="RELAY001",
                room_id="room",
                host_public_key="public-key",
            ),
        ),
    )


def test_reachable_direct_route_precedes_relay(monkeypatch) -> None:
    async def probe(url: str, _fingerprint: str) -> bool:
        return "10.0.0.8" in url

    monkeypatch.setattr(
        connection_manager.RemoteGatewayTransport,
        "probe",
        probe,
    )

    ordered = asyncio.run(connection_manager._probed_pairing_endpoints(invite()))

    assert [item.endpoint for item in ordered] == [
        "https://10.0.0.8:47632",
        "wss://relay.example.test",
        "https://192.168.8.128:47632",
    ]


def test_relay_precedes_unresponsive_direct_routes(monkeypatch) -> None:
    async def probe(_url: str, _fingerprint: str) -> bool:
        return False

    monkeypatch.setattr(
        connection_manager.RemoteGatewayTransport,
        "probe",
        probe,
    )

    ordered = asyncio.run(connection_manager._probed_pairing_endpoints(invite()))

    assert ordered[0].transport == "relay"
    assert len([item for item in ordered if item.transport == "direct"]) == 1
