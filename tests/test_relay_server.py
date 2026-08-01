from __future__ import annotations

import json
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from relay.server import create_application
from voice.relay_crypto import load_or_create_host_identity


@pytest.mark.asyncio
async def test_relay_routes_opaque_envelopes_without_modifying_them(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_RELAY_ALLOW_INSECURE", "1")
    identity = load_or_create_host_identity(tmp_path / "identity")
    application = create_application()

    async with TestServer(application) as server:
        base = str(server.make_url("/")).replace("http://", "ws://")
        async with aiohttp.ClientSession() as session:
            host = await session.ws_connect(base + "v1/host")
            hello = identity.sign_host_hello(int(time.time()), "relay-test-nonce")
            await host.send_json(hello)
            assert (await host.receive_json())["type"] == "host_ready"

            client = await session.ws_connect(base + f"v1/client/{identity.room_id}")
            opaque = {
                "protocol": 1,
                "room_id": identity.room_id,
                "request_id": "request-1",
                "client_public_key": "opaque-key",
                "nonce": "opaque-nonce",
                "ciphertext": "opaque-ciphertext",
            }
            await client.send_json({"type": "relay_request", "envelope": opaque})
            routed = await host.receive_json()
            assert routed["type"] == "relay_request"
            assert routed["envelope"] == opaque
            route_id = routed["route_id"]

            response = {**opaque, "ciphertext": "opaque-response"}
            await host.send_json(
                {"type": "relay_response", "route_id": route_id, "envelope": response}
            )
            delivered = await client.receive_json()
            assert delivered == {
                "type": "relay_response",
                "route_id": route_id,
                "envelope": response,
            }
            await client.close()
            await host.close()


@pytest.mark.asyncio
async def test_relay_rejects_tampered_host_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_RELAY_ALLOW_INSECURE", "1")
    identity = load_or_create_host_identity(tmp_path / "identity")
    application = create_application()

    async with TestServer(application) as server:
        base = str(server.make_url("/")).replace("http://", "ws://")
        async with aiohttp.ClientSession() as session:
            host = await session.ws_connect(base + "v1/host")
            hello = identity.sign_host_hello(int(time.time()), "tampered-nonce")
            hello["signature"] = "not-a-valid-signature"
            await host.send_str(json.dumps(hello))
            message = await host.receive()
            assert message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}
            assert host.close_code == 4001
