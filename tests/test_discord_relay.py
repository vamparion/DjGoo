from __future__ import annotations

import time

import pytest

from voice.discord_relay import (
    decode_discord_request,
    decode_discord_response,
    discord_message_url,
    discord_webhook_id,
    encode_discord_request,
    encode_discord_response,
    normalize_discord_webhook_url,
)
from voice.pairing_bundle import PairingEndpoint, PairingInvite


WEBHOOK = "https://discord.com/api/webhooks/1234567890/token_value"


def test_discord_webhook_normalization_and_message_url() -> None:
    value = WEBHOOK + "?wait=true"
    assert normalize_discord_webhook_url(value) == WEBHOOK
    assert discord_webhook_id(value) == 1234567890
    assert (
        discord_message_url(value, "555")
        == WEBHOOK + "/messages/555"
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://discord.com/api/webhooks/1/token",
        "https://example.com/api/webhooks/1/token",
        "https://discord.com/channels/1/2",
    ],
)
def test_discord_webhook_rejects_unsafe_urls(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_discord_webhook_url(value)


def test_discord_envelope_text_round_trip() -> None:
    envelope = {
        "protocol": 1,
        "room_id": "room",
        "request_id": "request",
        "ciphertext": "abc",
    }
    request = encode_discord_request(envelope)
    response = encode_discord_response(envelope)

    assert decode_discord_request(request) == envelope
    assert decode_discord_response(response) == envelope


def test_pairing_invite_orders_local_then_discord_then_hosted_relay() -> None:
    fingerprint = "a" * 64
    endpoints = (
        PairingEndpoint(
            transport="relay",
            endpoint="wss://relay.example",
            security=fingerprint,
            code="ABCD1234",
            room_id="room",
            host_public_key="key",
        ),
        PairingEndpoint(
            transport="discord",
            endpoint=WEBHOOK,
            security=fingerprint,
            code="EFGH5678",
            room_id="room",
            host_public_key="key",
        ),
        PairingEndpoint(
            transport="direct",
            endpoint="https://192.168.8.128:47632",
            security=fingerprint,
            code="IJKL9012",
        ),
    )
    invite = PairingInvite(
        code="",
        endpoints=endpoints,
        expires_at=time.time() + 60,
    )

    invite.validate()
    assert [
        endpoint.transport
        for endpoint in invite.ordered_endpoints()
    ] == ["direct", "discord", "relay"]
