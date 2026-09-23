from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from voice.command_acceptance import (
    AuthenticatedCommandProcessor,
    AuthorizationResult,
    CommandRejected,
)
from voice.pairing_store import PairingStore
from voice.relay_crypto import decrypt_response, encrypt_request, load_or_create_host_identity
from voice.relay_envelope import handle_host_envelope
from voice.webrtc_transport import RemoteStateRevision, WebRtcSession, WebRtcSignalManager


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


@pytest.mark.asyncio
async def test_same_command_envelope_across_transports_executes_once(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    device_id, token = _web_device(pairing)
    processor = _processor(tmp_path, pairing)
    command = {
        "intent": "toggle_pause",
        "command_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "confidence": 1,
        "device_id": device_id,
        "guild_id": "456",
    }

    direct = await processor.accept(token, command)
    fallback = await processor.accept(token, dict(command))

    assert direct["duplicate"] is False
    assert fallback == {"accepted": True, "duplicate": True, "command_id": command["command_id"]}
    assert len((tmp_path / "queue.jsonl").read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.asyncio
async def test_real_datachannel_state_command_and_revocation(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    device_id, token = _web_device(pairing)
    processor = _processor(tmp_path, pairing)
    manager = WebRtcSignalManager(processor, ice_servers=())
    processor.signal_provider = manager.signal
    client = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
    channel = client.createDataChannel("djgoo-control", ordered=True)
    messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    @channel.on("message")
    def on_message(raw: str) -> None:
        messages.put_nowait(json.loads(raw))

    offer = await client.createOffer()
    await client.setLocalDescription(offer)
    answer = await manager.signal(
        {
            "type": "offer",
            "session_id": str(uuid.uuid4()),
            "device_token": token,
            "offer": {
                "type": client.localDescription.type,
                "sdp": client.localDescription.sdp,
            },
        }
    )
    await client.setRemoteDescription(RTCSessionDescription(**answer["answer"]))

    async def response(request_id: str) -> dict[str, Any]:
        while True:
            message = await asyncio.wait_for(messages.get(), timeout=10)
            if message.get("type") == "response" and message.get("request_id") == request_id:
                return message

    for _ in range(100):
        if channel.readyState == "open":
            break
        await asyncio.sleep(0.05)
    assert channel.readyState == "open"

    channel.send(json.dumps({"type": "reconcile", "request_id": "state-1"}))
    state_response = await response("state-1")
    assert state_response["ok"] is True
    assert state_response["result"]["playback"]["state"] == "playing"

    command_id = str(uuid.uuid4())
    command = {
        "intent": "toggle_pause",
        "command_id": command_id,
        "created_at": time.time(),
        "confidence": 1,
        "device_id": device_id,
        "guild_id": "456",
    }
    channel.send(json.dumps({"type": "command", "request_id": "command-1", "command": command}))
    command_response = await response("command-1")
    assert command_response["ok"] is True
    assert command_response["result"]["command_id"] == command_id

    assert pairing.revoke_device(device_id, 123, 456)
    command["command_id"] = str(uuid.uuid4())
    channel.send(json.dumps({"type": "command", "request_id": "revoked-1", "command": command}))
    revoked = await response("revoked-1")
    assert revoked["ok"] is False
    assert revoked["status"] == 401

    await manager.close_all()
    await client.close()


@pytest.mark.asyncio
async def test_session_limit_and_shutdown_close_peers(tmp_path: Path) -> None:
    pairing = _store(tmp_path)
    processor = _processor(tmp_path, pairing)
    manager = WebRtcSignalManager(processor, max_sessions=1)

    class Peer:
        def __init__(self) -> None:
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    first_peer = Peer()
    second_peer = Peer()
    first = WebRtcSession("first", "device-1", 1, 1, "token-1", peer=first_peer)
    second = WebRtcSession("second", "device-2", 2, 2, "token-2", peer=second_peer)
    manager._sessions = {"first": first, "second": second}

    await manager._enforce_session_limit()
    assert first_peer.closed == 1
    assert first.closed is True
    await manager.close_all()
    assert second_peer.closed == 1
    await manager.close_all()
    assert second_peer.closed == 1
