from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_pairing_uses_outbound_route_without_waiting_for_lan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def pair(invite, **kwargs):
        calls.append(tuple(endpoint.transport for endpoint in invite.endpoints))
        return "credential", "discord"

    async def discover(*args, **kwargs):
        raise AssertionError("LAN discovery must not run after outbound pairing succeeds")

    monkeypatch.setattr(discovery_connection, "_pair_from_invite", pair)
    monkeypatch.setattr(discovery_connection, "discover_gateway_urls", discover)
    invite = PairingInvite(
        code="",
        endpoints=(
            PairingEndpoint(
                transport="discord",
                endpoint=(
                    "https://discord.com/api/webhooks/"
                    "123456789012345678/test-webhook-token"
                ),
                security="a" * 64,
                code="OUTB1234",
                room_id="room",
                host_public_key="public-key",
            ),
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security="b" * 64,
                code="LAND1234",
            ),
        ),
        expires_at=time.time() + 60,
    )

    result = await discovery_connection.pair_from_invite_with_discovery(
        invite,
        device_name="Recipient",
        credential_path=tmp_path / "credential.json",
    )

    assert result == ("credential", "discord")
    assert calls == [("discord",)]


@pytest.mark.asyncio
async def test_pairing_uses_lan_only_after_outbound_route_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def pair(invite, **kwargs):
        transports = tuple(endpoint.transport for endpoint in invite.endpoints)
        calls.append(transports)
        if transports == ("discord",):
            raise RuntimeError("outbound unavailable")
        return "credential", "direct"

    async def discover(*args, **kwargs):
        return ["https://192.168.8.50:47632"]

    monkeypatch.setattr(discovery_connection, "_pair_from_invite", pair)
    monkeypatch.setattr(discovery_connection, "discover_gateway_urls", discover)
    invite = PairingInvite(
        code="",
        endpoints=(
            PairingEndpoint(
                transport="discord",
                endpoint=(
                    "https://discord.com/api/webhooks/"
                    "123456789012345678/test-webhook-token"
                ),
                security="a" * 64,
                code="OUTB1234",
                room_id="room",
                host_public_key="public-key",
            ),
            PairingEndpoint(
                transport="direct",
                endpoint="https://192.168.8.128:47632",
                security="b" * 64,
                code="LAND1234",
            ),
        ),
        expires_at=time.time() + 60,
    )

    result = await discovery_connection.pair_from_invite_with_discovery(
        invite,
        device_name="Recipient",
        credential_path=tmp_path / "credential.json",
    )

    assert result == ("credential", "direct")
    assert calls == [("discord",), ("direct", "direct")]
