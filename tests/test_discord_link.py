from __future__ import annotations

from pathlib import Path

import pytest

from voice.discord_link_host import DiscordLinkHostProcessor
from voice.discord_link_transport import (
    REQUEST_PREFIX,
    RESPONSE_PREFIX,
    decode_discord_envelope,
    encode_discord_envelope,
    fingerprint_public_key,
    normalize_webhook_url,
)
from voice.relay_crypto import (
    decrypt_response,
    encrypt_response,
    encrypt_request,
    load_or_create_host_identity,
)


def test_large_response_uses_compression_and_round_trips(tmp_path: Path) -> None:
    identity = load_or_create_host_identity(tmp_path / "identity")
    _request, request_key = encrypt_request(
        identity.encryption_public_b64,
        "room",
        "large-response",
        {"action": "status", "payload": {}},
    )
    payload = {"ok": True, "result": {"history": [{"title": "Song", "artist": "Artist"}] * 1500}}
    envelope = encrypt_response(
        request_key.private_key.public_key(),
        "room",
        "large-response",
        payload,
    )
    assert envelope["encoding"] == "gzip-json"
    assert decrypt_response(request_key, envelope) == payload


class FakeCommands:
    async def redeem_pairing(self, code: str, device_name: str):
        assert code == "ABCD2345"
        return {
            "device_id": "device",
            "device_token": "token",
            "discord_user_id": "123",
            "guild_id": "456",
            "device_name": device_name,
        }

    async def accept(self, token: str, payload: dict):
        assert token == "token"
        return {
            "accepted": True,
            "command_id": payload["command_id"],
        }

    async def status(self, token: str):
        assert token == "token"
        return {"status": "connected"}


def test_official_discord_webhook_validation() -> None:
    url = (
        "https://discord.com/api/webhooks/"
        "123456789012345678/abcdefghijklmnopqrstuvwxyz"
    )

    normalized, webhook_id = normalize_webhook_url(url)

    assert normalized == url
    assert webhook_id == "123456789012345678"
    with pytest.raises(ValueError):
        normalize_webhook_url(
            "https://example.com/api/webhooks/123/token"
        )


def test_discord_envelope_content_round_trip() -> None:
    envelope = {
        "room_id": "123",
        "request_id": "request",
        "ciphertext": "opaque",
    }

    content = encode_discord_envelope(REQUEST_PREFIX, envelope)

    assert decode_discord_envelope(REQUEST_PREFIX, content) == envelope
    with pytest.raises(ValueError):
        decode_discord_envelope(RESPONSE_PREFIX, content)


@pytest.mark.asyncio
async def test_encrypted_pairing_round_trip(tmp_path: Path) -> None:
    identity = load_or_create_host_identity(
        tmp_path / "identity"
    )
    host = DiscordLinkHostProcessor(
        identity,
        FakeCommands(),
    )
    webhook_id = "123456789012345678"
    request_id = "request-id"
    request, request_key = encrypt_request(
        identity.encryption_public_b64,
        webhook_id,
        request_id,
        {
            "action": "pair",
            "payload": {
                "code": "ABCD2345",
                "device_name": "Player PC",
            },
        },
    )

    encrypted_response = await host.handle(
        request,
        webhook_id=webhook_id,
    )
    response = decrypt_response(
        request_key,
        encrypted_response,
    )

    assert response["ok"] is True
    assert response["status"] == 201
    assert response["result"]["device_id"] == "device"
    assert fingerprint_public_key(
        identity.encryption_public_b64
    ) == identity.encryption_fingerprint_sha256


@pytest.mark.asyncio
async def test_wrong_webhook_room_is_rejected(tmp_path: Path) -> None:
    identity = load_or_create_host_identity(
        tmp_path / "identity"
    )
    host = DiscordLinkHostProcessor(
        identity,
        FakeCommands(),
    )
    request, _request_key = encrypt_request(
        identity.encryption_public_b64,
        "room-one",
        "request-id",
        {
            "action": "status",
            "payload": {"device_token": "token"},
        },
    )

    with pytest.raises(ValueError, match="wrong webhook"):
        await host.handle(
            request,
            webhook_id="room-two",
        )
