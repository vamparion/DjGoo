from __future__ import annotations

import time
import uuid
from pathlib import Path

from voice.pairing_store import PairingStore


def store(tmp_path: Path) -> PairingStore:
    return PairingStore(tmp_path / "pairing.db", tmp_path / "pairing-secret.bin")


def test_pairing_code_is_one_time_and_token_authenticates(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    code = pairing.create_pairing_code(123, 456, ttl_seconds=300)
    redeemed = pairing.redeem_pairing_code(code, "Gaming PC")
    assert redeemed is not None
    identity, token = redeemed
    assert identity.user_id == 123
    assert identity.guild_id == 456
    assert identity.device_name == "Gaming PC"
    assert pairing.redeem_pairing_code(code, "Second PC") is None
    authenticated = pairing.authenticate(token)
    assert authenticated is not None
    assert authenticated.device_id == identity.device_id


def test_expired_code_cannot_be_redeemed(tmp_path: Path, monkeypatch) -> None:
    pairing = store(tmp_path)
    now = time.time()
    monkeypatch.setattr("voice.pairing_store.time.time", lambda: now)
    code = pairing.create_pairing_code(1, 2, ttl_seconds=60)
    monkeypatch.setattr("voice.pairing_store.time.time", lambda: now + 61)
    assert pairing.redeem_pairing_code(code, "Expired") is None


def test_revocation_invalidates_only_selected_device(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    first_identity, first_token = pairing.redeem_pairing_code(
        pairing.create_pairing_code(10, 20), "First"
    )
    second_identity, second_token = pairing.redeem_pairing_code(
        pairing.create_pairing_code(10, 20), "Second"
    )
    assert pairing.revoke_device(first_identity.device_id, 10, 20)
    assert pairing.authenticate(first_token) is None
    assert pairing.authenticate(second_token) is not None
    assert [device.device_id for device in pairing.list_devices(10, 20)] == [second_identity.device_id]


def test_command_receipts_are_idempotent(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    identity, _ = pairing.redeem_pairing_code(pairing.create_pairing_code(10, 20), "PC")
    command_id = str(uuid.uuid4())
    assert pairing.claim_command(command_id, identity.device_id)
    assert not pairing.claim_command(command_id, identity.device_id)
    assert not pairing.claim_command("not-a-uuid", identity.device_id)


def test_user_deletion_removes_devices_and_pairing_codes(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    code = pairing.create_pairing_code(77, 88)
    identity, token = pairing.redeem_pairing_code(code, "PC")
    pairing.create_pairing_code(77, 88)
    pairing.delete_user(77)
    assert pairing.authenticate(token) is None
    assert pairing.list_devices(77, 88) == []
    assert not pairing.claim_command(str(uuid.uuid4()), identity.device_id)
