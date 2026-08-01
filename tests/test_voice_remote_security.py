from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice.remote_transport import (
    RemoteCredential,
    load_credential,
    normalize_fingerprint,
    normalize_gateway_url,
    save_credential,
)
from voice.tls_identity import certificate_fingerprint, ensure_tls_identity


def test_gateway_requires_https() -> None:
    assert normalize_gateway_url("https://192.168.1.2:47632") == "https://192.168.1.2:47632/"
    with pytest.raises(ValueError):
        normalize_gateway_url("http://192.168.1.2:47632")


def test_fingerprint_normalization() -> None:
    raw = "AA:" * 31 + "AA"
    assert normalize_fingerprint(raw) == "aa" * 32
    with pytest.raises(ValueError):
        normalize_fingerprint("abcd")


def test_tls_identity_is_stable(tmp_path: Path) -> None:
    certificate = tmp_path / "gateway.crt.pem"
    private_key = tmp_path / "gateway.key.pem"
    first = ensure_tls_identity(certificate, private_key)
    second = ensure_tls_identity(certificate, private_key)
    assert first.fingerprint_sha256 == second.fingerprint_sha256
    assert first.fingerprint_sha256 == certificate_fingerprint(certificate)
    assert len(private_key.read_bytes()) > 1000


def test_remote_credential_round_trip_and_redaction(tmp_path: Path) -> None:
    credential = RemoteCredential(
        gateway_url="https://djgoo.local:47632",
        tls_fingerprint_sha256="ab" * 32,
        device_id="device-id",
        device_token="secret-device-token",
        discord_user_id="123",
        guild_id="456",
    )
    path = tmp_path / "credential.json"
    save_credential(path, credential)
    loaded = load_credential(path)
    assert loaded == credential
    assert loaded.redacted()["device_token"] == "<redacted>"
    assert json.loads(path.read_text(encoding="utf-8"))["device_token"] == "secret-device-token"
