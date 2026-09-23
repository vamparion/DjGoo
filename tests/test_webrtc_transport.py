from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from voice.command_acceptance import (
    AuthenticatedCommandProcessor,
    AuthorizationResult,
    CommandRejected,
)
from voice.pairing_store import PairingStore
from voice.relay_crypto import decrypt_response, encrypt_request, load_or_create_host_identity
from voice.relay_envelope import handle_host_envelope
from voice.webrtc_transport import RemoteStateRevision, WebRtcSignalManager


def _store(tmp_path: Path) -> PairingStore:
    return PairingStore(tmp_path / "pairing.db", tmp_path / "secret.bin")


async def _authorize(_identity, _intent: str) -> AuthorizationResult:
    return AuthorizationResult(True, actor_role="member")


def _web_device(pairing: PairingStore) -> tuple[str, str]:
    code = pairing.create_pairing_code(
        123,
        456,
        device_type="web",
        capabilities=("state.read", "playback.control"),
    )
    redeemed = pairing.redeem_pairing_code(code, "Browser")
    assert redeemed is not None
    identity, token = redeemed
    return identity.device_id, token


def _processor(tmp_path: Path, pairing: PairingStore) -> AuthenticatedCommandProcessor:
    async def state(_identity):
        return {"playback": {"state": "playing"}, "queue": []}

    return AuthenticatedCommandProcessor(
        pairing,
        tmp_path / "queue.jsonl",
        _authorize,
        state,
    )


@pytest.mark.asyncio
async def test_webrtc_signal_requires_valid_device_token(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    processor = _processor(tmp_path, pairing)
    manager = WebRtcSignalManager(processor)
    processor.signal_provider = manager.signal

    with pytest.raises(CommandRejected) as rejected:
        await processor.webrtc_signal({"type": "status", "device_token": "bad"})

    assert rejected.value.status == 401


@pytest.mark.asyncio
async def test_webrtc_status_is_authenticated_and_does_not_require_aiortc(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    _device_id, token = _web_device(pairing)
    processor = _processor(tmp_path, pairing)
    manager = WebRtcSignalManager(processor, ice_servers=("stun:example.test:3478",))
    processor.signal_provider = manager.signal

    status = await processor.webrtc_signal({"type": "status", "device_token": token})

    assert status["ice_servers"] == ("stun:example.test:3478",)
    assert status["sessions"] == []
    assert isinstance(status["available"], bool)


@pytest.mark.asyncio
async def test_encrypted_relay_dispatches_webrtc_signal(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    _device_id, token = _web_device(pairing)
    processor = _processor(tmp_path, pairing)

    async def signal(payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["device_token"] == token
        return {"accepted": True, "direct": "ready"}

    processor.signal_provider = signal
    identity = load_or_create_host_identity(tmp_path / "identity")
    request_id = str(uuid.uuid4())
    envelope, request_key = encrypt_request(
        identity.encryption_public_b64,
        identity.room_id,
        request_id,
        {
            "action": "webrtc/signal",
            "payload": {"type": "status", "device_token": token},
        },
    )

    response_envelope = await handle_host_envelope(identity, processor, envelope)
    response = decrypt_response(request_key, response_envelope)

    assert response["ok"] is True
    assert response["result"] == {"accepted": True, "direct": "ready"}


def test_state_revision_advances_on_meaningful_changes() -> None:
    revision = RemoteStateRevision()

    first = revision.snapshot({"playback": {"title": "One"}, "queue": []})
    duplicate = revision.snapshot({"playback": {"title": "One"}, "queue": []})
    changed = revision.snapshot({"playback": {"title": "Two"}, "queue": []})
    queue_changed = revision.snapshot({"playback": {"title": "Two"}, "queue": [{"id": "1"}]})

    assert first["revision"] == duplicate["revision"]
    assert changed["revision"] == first["revision"] + 1
    assert queue_changed["queue_revision"] == changed["queue_revision"] + 1


def test_pairing_store_keeps_sibling_route_codes(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    first = pairing.create_pairing_code(1, 2, ttl_seconds=300, device_type="web")
    second = pairing.create_pairing_code(1, 2, ttl_seconds=300, device_type="web")

    assert pairing.redeem_pairing_code(first, "First browser") is not None
    assert pairing.redeem_pairing_code(second, "Second browser") is not None
