from __future__ import annotations

import time

import pytest

from voice.pairing_bundle import build_invite, parse_invite


def test_pairing_invite_round_trip_with_direct_and_relay() -> None:
    invite = build_invite(
        code="ABCD2345",
        expires_at=time.time() + 300,
        direct_url="https://192.168.1.5:47632",
        direct_fingerprint="ab" * 32,
        relay_url="wss://relay.example.test",
        relay_fingerprint="cd" * 32,
        room_id="room-id",
        host_public_key="host-public-key",
        host_name="Living Room DjGoo",
        guild_name="Game Night",
    )

    parsed = parse_invite(invite.to_uri())

    assert parsed.code == "ABCD2345"
    assert [endpoint.transport for endpoint in parsed.ordered_endpoints()] == [
        "direct",
        "relay",
    ]
    assert parsed.host_name == "Living Room DjGoo"
    assert len(parsed.safety_number()) == 6


def test_expired_pairing_invite_is_rejected() -> None:
    invite = build_invite(
        code="ABCD2345",
        expires_at=time.time() - 1,
        direct_url="https://192.168.1.5:47632",
        direct_fingerprint="ab" * 32,
    )

    with pytest.raises(ValueError, match="expired"):
        parse_invite(invite.to_uri())


def test_pairing_invite_rejects_unpinned_direct_endpoint() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        build_invite(
            code="ABCD2345",
            expires_at=time.time() + 300,
            direct_url="https://192.168.1.5:47632",
            direct_fingerprint="abcd",
        )


def test_pairing_invite_rejects_insecure_relay() -> None:
    with pytest.raises(ValueError, match="wss"):
        build_invite(
            code="ABCD2345",
            expires_at=time.time() + 300,
            relay_url="ws://relay.example.test",
            relay_fingerprint="cd" * 32,
            room_id="room-id",
            host_public_key="host-public-key",
        )
