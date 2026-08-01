from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from voice.relay_crypto import (
    decrypt_request,
    decrypt_response,
    encrypt_request,
    encrypt_response,
    load_or_create_host_identity,
    verify_host_hello,
)


def test_host_identity_is_stable_and_hello_is_signed(tmp_path: Path) -> None:
    first = load_or_create_host_identity(tmp_path)
    second = load_or_create_host_identity(tmp_path)
    assert first.room_id == second.room_id
    assert first.encryption_public_b64 == second.encryption_public_b64

    now = int(time.time())
    hello = first.sign_host_hello(now, "nonce-one")
    assert verify_host_hello(hello, now=now) == first.room_id

    tampered = dict(hello)
    tampered["room_id"] = "wrong-room"
    with pytest.raises(ValueError):
        verify_host_hello(tampered, now=now)
    with pytest.raises(ValueError):
        verify_host_hello(hello, now=now + 120)


def test_request_and_response_are_end_to_end_encrypted(tmp_path: Path) -> None:
    host = load_or_create_host_identity(tmp_path)
    request_id = str(uuid.uuid4())
    plaintext = {
        "action": "command",
        "payload": {"device_token": "private-token", "intent": "skip", "raw": "skip"},
    }
    envelope, request_key = encrypt_request(
        host.encryption_public_b64,
        host.room_id,
        request_id,
        plaintext,
    )
    serialized = str(envelope)
    assert "private-token" not in serialized
    assert "skip" not in serialized

    decrypted, client_public = decrypt_request(host.encryption_private_key, envelope)
    assert decrypted == plaintext

    response = encrypt_response(
        client_public,
        host.room_id,
        request_id,
        {"ok": True, "result": {"accepted": True}},
    )
    assert decrypt_response(request_key, response) == {
        "ok": True,
        "result": {"accepted": True},
    }


def test_ciphertext_tampering_is_rejected(tmp_path: Path) -> None:
    host = load_or_create_host_identity(tmp_path)
    request_id = str(uuid.uuid4())
    envelope, _ = encrypt_request(
        host.encryption_public_b64,
        host.room_id,
        request_id,
        {"action": "pair", "payload": {"code": "ABCDEFGH"}},
    )
    tampered = copy.deepcopy(envelope)
    ciphertext = tampered["ciphertext"]
    tampered["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    with pytest.raises((InvalidTag, ValueError)):
        decrypt_request(host.encryption_private_key, tampered)
