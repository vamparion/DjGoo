from __future__ import annotations

import asyncio
import time

from voice.connection_manager import _probed_pairing_endpoints
from voice.pairing_bundle import PairingEndpoint, PairingInvite
from voice.remote_transport import RemoteGatewayTransport


def test_unreachable_direct_route_moves_behind_discord_fallback(
    monkeypatch,
) -> None:
    async def probe(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(RemoteGatewayTransport, "probe", probe)
    fingerprint = "b" * 64
    invite = PairingInvite(
        code="",
        endpoints=(
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security=fingerprint,
                code="ABCD1234",
            ),
            PairingEndpoint(
                transport="discord",
                endpoint=(
                    "https://discord.com/api/webhooks/"
                    "1234567890/token_value"
                ),
                security=fingerprint,
                code="EFGH5678",
                room_id="room",
                host_public_key="key",
            ),
            PairingEndpoint(
                transport="relay",
                endpoint="wss://relay.example",
                security=fingerprint,
                code="IJKL9012",
                room_id="room",
                host_public_key="key",
            ),
        ),
        expires_at=time.time() + 60,
    )

    ordered = asyncio.run(_probed_pairing_endpoints(invite))

    assert [item.transport for item in ordered] == [
        "discord",
        "relay",
        "direct",
    ]
