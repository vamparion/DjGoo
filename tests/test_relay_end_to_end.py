from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer

from relay.server import STATE_KEY, create_application
from voice.command_acceptance import AuthenticatedCommandProcessor, AuthorizationResult
from voice.command_queue import drain_queue
from voice.pairing_store import PairingStore
from voice.relay_crypto import load_or_create_host_identity
from voice.relay_host import RelayHostClient
from voice.relay_transport import RelayTransport


@pytest.mark.asyncio
async def test_encrypted_pairing_and_command_delivery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_RELAY_ALLOW_INSECURE", "1")
    application = create_application()
    pairing_store = PairingStore(tmp_path / "pairing.db", tmp_path / "pairing-secret.bin")
    queue_path = tmp_path / "remote-commands.jsonl"

    async def authorize(identity, intent: str) -> AuthorizationResult:
        assert identity.user_id == 123
        assert identity.guild_id == 456
        assert intent == "play"
        return AuthorizationResult(True, voice_channel_id=789)

    processor = AuthenticatedCommandProcessor(pairing_store, queue_path, authorize)
    identity = load_or_create_host_identity(tmp_path / "relay-identity")

    async with TestServer(application) as server:
        relay_url = str(server.make_url("/")).replace("http://", "ws://")
        host = RelayHostClient(relay_url, identity, processor)
        host.start()
        try:
            for _ in range(100):
                if identity.room_id in application[STATE_KEY].hosts:
                    break
                await asyncio.sleep(0.02)
            assert identity.room_id in application[STATE_KEY].hosts

            code = pairing_store.create_pairing_code(123, 456)
            credential = await RelayTransport.pair(
                relay_url,
                identity.room_id,
                code,
                identity.encryption_public_b64,
                identity.encryption_fingerprint_sha256,
                device_name="Remote Gaming PC",
            )
            assert credential.discord_user_id == "123"
            assert credential.guild_id == "456"

            transport = RelayTransport(credential)
            command_id = str(uuid.uuid4())
            response = await transport.send_async(
                {
                    "type": "command",
                    "source": "voice_remote",
                    "created_at": time.time(),
                    "command_id": command_id,
                    "intent": "play",
                    "query": "Sandstorm",
                    "playlist": "",
                    "value": None,
                    "confidence": 0.91,
                    "raw": "play Sandstorm",
                }
            )
            assert response == {
                "accepted": True,
                "duplicate": False,
                "command_id": command_id,
            }
            items = drain_queue(queue_path)
            assert len(items) == 1
            assert items[0]["user_id"] == 123
            assert items[0]["guild_id"] == 456
            assert items[0]["voice_channel_id"] == 789
            assert items[0]["query"] == "Sandstorm"
        finally:
            await host.stop()
