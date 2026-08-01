from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from voice import connection_manager
from voice.pairing_bundle import build_invite
from voice.relay_transport import RelayCredential
from voice.remote_transport import RemoteCredential


@pytest.mark.asyncio
async def test_pairing_one_route_stores_all_pinned_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated = RemoteCredential(
        gateway_url="https://host.local:47632",
        tls_fingerprint_sha256="ab" * 32,
        device_id="one-device",
        device_token="one-token",
        discord_user_id="123",
        guild_id="456",
    )

    async def pair_direct(*args, **kwargs):
        return authenticated

    monkeypatch.setattr(
        connection_manager.RemoteGatewayTransport,
        "pair",
        pair_direct,
    )
    invite = build_invite(
        expires_at=4_102_444_800,
        direct_url="https://host.local:47632",
        direct_fingerprint="ab" * 32,
        direct_code="ABCD2345",
        relay_url="wss://relay.example.test",
        relay_fingerprint="cd" * 32,
        relay_code="WXYZ6789",
        room_id="room",
        host_public_key="relay-public-key",
    )
    path = tmp_path / "recipient.json"

    primary, selected = await connection_manager.pair_from_invite(
        invite,
        device_name="Player PC",
        credential_path=path,
    )
    credentials, preferred = connection_manager.load_recipient_credentials(path)

    assert selected == "direct"
    assert primary.device_id == "one-device"
    assert preferred == "direct"
    assert [credential.transport for credential in credentials] == [
        "direct",
        "relay",
    ]
    assert {credential.device_token for credential in credentials} == {
        "one-token"
    }


@pytest.mark.asyncio
async def test_failover_reuses_command_uuid_and_promotes_working_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = RemoteCredential(
        gateway_url="https://host.local:47632",
        tls_fingerprint_sha256="ab" * 32,
        device_id="device",
        device_token="token",
        discord_user_id="123",
        guild_id="456",
    )
    relay = RelayCredential(
        transport="relay",
        relay_url="wss://relay.example.test",
        room_id="room",
        host_encryption_public_key="public-key",
        host_encryption_fingerprint_sha256="cd" * 32,
        device_id="device",
        device_token="token",
        discord_user_id="123",
        guild_id="456",
    )
    seen_ids: list[str] = []

    class FakeTransport:
        def __init__(self, credential, *, fails: bool) -> None:
            self.credential = credential
            self.fails = fails

        async def send_async(self, item):
            seen_ids.append(str(item["command_id"]))
            if self.fails:
                raise OSError("route unavailable")
            return {"accepted": True, "command_id": item["command_id"]}

        async def status_async(self):
            return {"status": "connected"}

    def fake_transport(credential):
        return FakeTransport(
            credential,
            fails=credential.transport == "direct",
        )

    monkeypatch.setattr(
        connection_manager,
        "transport_for_credential",
        fake_transport,
    )
    path = tmp_path / "recipient.json"
    connection_manager._save_connection(
        path,
        [direct, relay],
        preferred_transport="direct",
    )
    transport = connection_manager.load_recipient_transport(path)

    result = await transport.send_async(
        {"intent": "skip", "created_at": 1.0}
    )
    _credentials, preferred = connection_manager.load_recipient_credentials(path)

    assert result["transport"] == "relay"
    assert len(seen_ids) == 2
    assert len(set(seen_ids)) == 1
    assert preferred == "relay"
