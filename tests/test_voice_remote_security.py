from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice import secure_store
from voice.command_gateway import AuthorizationResult
from voice.remote_transport import (
    RemoteCredential,
    load_credential,
    normalize_fingerprint,
    normalize_gateway_url,
    save_credential,
)
from voice.tls_identity import certificate_fingerprint, ensure_tls_identity


def test_gateway_authorization_carries_server_derived_role() -> None:
    result = AuthorizationResult(True, voice_channel_id=42, actor_role="host")
    assert result.actor_role == "host"


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
    assert certificate.read_text(encoding="ascii").startswith("-----BEGIN CERTIFICATE-----")
    assert private_key.read_text(encoding="ascii").startswith("-----BEGIN " + "PRIVATE KEY-----")


def test_remote_credential_is_dpapi_protected_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the Windows envelope without changing process-wide os.name on the
    # Linux CI runner or requiring CryptProtectData to exist there. Construct
    # the fake token at runtime so repository secret scanning remains strict.
    test_token = "test-device-" + "credential"
    monkeypatch.setattr(secure_store, "_is_windows", lambda: True)
    monkeypatch.setattr(secure_store, "_protect_windows", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect_windows", lambda value: value[::-1])

    credential = RemoteCredential(
        gateway_url="https://djgoo.local:47632",
        tls_fingerprint_sha256="ab" * 32,
        device_id="device-id",
        device_token=test_token,
        discord_user_id="123",
        guild_id="456",
    )
    path = tmp_path / "credential.json"
    save_credential(path, credential)
    loaded = load_credential(path)

    assert loaded == credential
    assert loaded.redacted()["device_token"] == "<redacted>"
    raw = path.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert envelope["protection"] == "windows-dpapi-current-user"
    assert test_token not in raw


def test_plaintext_alpha_credential_is_migratable(tmp_path: Path) -> None:
    path = tmp_path / "credential.json"
    old_token = "old-test-token-" + "value-long-enough"
    path.write_text(
        json.dumps(
            {
                "gateway_url": "https://djgoo.local:47632",
                "tls_fingerprint_sha256": "cd" * 32,
                "device_id": "old-device",
                "device_token": old_token,
                "discord_user_id": "123",
                "guild_id": "456",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_credential(path)
    assert loaded.device_id == "old-device"
    assert loaded.device_token == old_token
    assert loaded.transport == "direct"
