from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


PROTOCOL_VERSION = 1
MAX_ENCRYPTED_PAYLOAD_BYTES = 32_768


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    normalized = value.strip()
    padding = "=" * ((4 - len(normalized) % 4) % 4)
    return base64.urlsafe_b64decode(normalized + padding)


def public_key_bytes(key: x25519.X25519PublicKey | ed25519.Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def room_id_for_signing_key(public_key: ed25519.Ed25519PublicKey) -> str:
    digest = hashlib.sha256(public_key_bytes(public_key)).digest()
    return _b64encode(digest[:18])


def fingerprint_for_key(public_key: x25519.X25519PublicKey | ed25519.Ed25519PublicKey) -> str:
    return hashlib.sha256(public_key_bytes(public_key)).hexdigest()


def _derive_key(shared_secret: bytes, room_id: str, request_id: str, purpose: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=hashlib.sha256(room_id.encode("utf-8")).digest(),
        info=f"djgoo-relay-v{PROTOCOL_VERSION}:{request_id}:{purpose}".encode("utf-8"),
    ).derive(shared_secret)


def _aad(room_id: str, request_id: str, purpose: str) -> bytes:
    return f"djgoo-relay-v{PROTOCOL_VERSION}|{room_id}|{request_id}|{purpose}".encode("utf-8")


@dataclass(frozen=True)
class RelayHostIdentity:
    signing_private_key: ed25519.Ed25519PrivateKey
    encryption_private_key: x25519.X25519PrivateKey

    @property
    def signing_public_key(self) -> ed25519.Ed25519PublicKey:
        return self.signing_private_key.public_key()

    @property
    def encryption_public_key(self) -> x25519.X25519PublicKey:
        return self.encryption_private_key.public_key()

    @property
    def room_id(self) -> str:
        return room_id_for_signing_key(self.signing_public_key)

    @property
    def encryption_public_b64(self) -> str:
        return _b64encode(public_key_bytes(self.encryption_public_key))

    @property
    def encryption_fingerprint_sha256(self) -> str:
        return fingerprint_for_key(self.encryption_public_key)

    @property
    def signing_public_b64(self) -> str:
        return _b64encode(public_key_bytes(self.signing_public_key))

    def sign_host_hello(self, timestamp: int, nonce: str) -> dict[str, Any]:
        message = f"{PROTOCOL_VERSION}|{self.room_id}|{timestamp}|{nonce}".encode("utf-8")
        return {
            "type": "host_hello",
            "protocol": PROTOCOL_VERSION,
            "room_id": self.room_id,
            "timestamp": int(timestamp),
            "nonce": nonce,
            "signing_public_key": self.signing_public_b64,
            "signature": _b64encode(self.signing_private_key.sign(message)),
        }


def load_or_create_host_identity(directory: Path) -> RelayHostIdentity:
    directory.mkdir(parents=True, exist_ok=True)
    signing_path = directory / "relay-signing-ed25519.key"
    encryption_path = directory / "relay-encryption-x25519.key"

    def load_or_create(path: Path, factory, loader):
        if path.exists():
            raw = path.read_bytes()
            if len(raw) != 32:
                raise ValueError(f"Relay key has an invalid length: {path}")
            return loader(raw)
        key = factory()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        temp = path.with_suffix(".tmp")
        temp.write_bytes(raw)
        temp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    return RelayHostIdentity(
        signing_private_key=load_or_create(
            signing_path,
            ed25519.Ed25519PrivateKey.generate,
            ed25519.Ed25519PrivateKey.from_private_bytes,
        ),
        encryption_private_key=load_or_create(
            encryption_path,
            x25519.X25519PrivateKey.generate,
            x25519.X25519PrivateKey.from_private_bytes,
        ),
    )


def verify_host_hello(payload: dict[str, Any], *, now: int, max_age_seconds: int = 60) -> str:
    try:
        protocol = int(payload["protocol"])
        room_id = str(payload["room_id"])
        timestamp = int(payload["timestamp"])
        nonce = str(payload["nonce"])
        signing_public_raw = _b64decode(str(payload["signing_public_key"]))
        signature = _b64decode(str(payload["signature"]))
    except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
        raise ValueError("Invalid relay host hello") from exc
    if protocol != PROTOCOL_VERSION:
        raise ValueError("Unsupported relay protocol")
    if not nonce or len(nonce) > 128:
        raise ValueError("Invalid relay host nonce")
    if abs(int(now) - timestamp) > max_age_seconds:
        raise ValueError("Relay host hello is stale")
    public_key = ed25519.Ed25519PublicKey.from_public_bytes(signing_public_raw)
    if room_id_for_signing_key(public_key) != room_id:
        raise ValueError("Relay room does not match signing key")
    message = f"{protocol}|{room_id}|{timestamp}|{nonce}".encode("utf-8")
    try:
        public_key.verify(signature, message)
    except Exception as exc:
        raise ValueError("Relay host signature is invalid") from exc
    return room_id


@dataclass(frozen=True)
class ClientRequestKey:
    private_key: x25519.X25519PrivateKey

    @classmethod
    def generate(cls) -> "ClientRequestKey":
        return cls(x25519.X25519PrivateKey.generate())

    @property
    def public_b64(self) -> str:
        return _b64encode(public_key_bytes(self.private_key.public_key()))


def encrypt_request(
    host_public_key_b64: str,
    room_id: str,
    request_id: str,
    plaintext: dict[str, Any],
    *,
    request_key: ClientRequestKey | None = None,
) -> tuple[dict[str, Any], ClientRequestKey]:
    request_key = request_key or ClientRequestKey.generate()
    host_public = x25519.X25519PublicKey.from_public_bytes(_b64decode(host_public_key_b64))
    shared = request_key.private_key.exchange(host_public)
    key = _derive_key(shared, room_id, request_id, "request")
    nonce = secrets.token_bytes(12)
    encoded = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_ENCRYPTED_PAYLOAD_BYTES:
        raise ValueError("Relay request is too large")
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, encoded, _aad(room_id, request_id, "request"))
    return (
        {
            "protocol": PROTOCOL_VERSION,
            "room_id": room_id,
            "request_id": request_id,
            "client_public_key": request_key.public_b64,
            "nonce": _b64encode(nonce),
            "ciphertext": _b64encode(ciphertext),
        },
        request_key,
    )


def decrypt_request(
    host_private_key: x25519.X25519PrivateKey,
    envelope: dict[str, Any],
) -> tuple[dict[str, Any], x25519.X25519PublicKey]:
    room_id = str(envelope["room_id"])
    request_id = str(envelope["request_id"])
    client_public = x25519.X25519PublicKey.from_public_bytes(_b64decode(str(envelope["client_public_key"])))
    nonce = _b64decode(str(envelope["nonce"]))
    ciphertext = _b64decode(str(envelope["ciphertext"]))
    if len(ciphertext) > MAX_ENCRYPTED_PAYLOAD_BYTES + 32:
        raise ValueError("Relay request is too large")
    shared = host_private_key.exchange(client_public)
    key = _derive_key(shared, room_id, request_id, "request")
    decoded = ChaCha20Poly1305(key).decrypt(
        nonce,
        ciphertext,
        _aad(room_id, request_id, "request"),
    )
    payload = json.loads(decoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Relay request must decrypt to an object")
    return payload, client_public


def encrypt_response(
    client_public_key: x25519.X25519PublicKey,
    room_id: str,
    request_id: str,
    plaintext: dict[str, Any],
) -> dict[str, Any]:
    ephemeral = x25519.X25519PrivateKey.generate()
    shared = ephemeral.exchange(client_public_key)
    key = _derive_key(shared, room_id, request_id, "response")
    nonce = secrets.token_bytes(12)
    encoded = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_ENCRYPTED_PAYLOAD_BYTES:
        raise ValueError("Relay response is too large")
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, encoded, _aad(room_id, request_id, "response"))
    return {
        "protocol": PROTOCOL_VERSION,
        "room_id": room_id,
        "request_id": request_id,
        "host_ephemeral_public_key": _b64encode(public_key_bytes(ephemeral.public_key())),
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
    }


def decrypt_response(request_key: ClientRequestKey, envelope: dict[str, Any]) -> dict[str, Any]:
    room_id = str(envelope["room_id"])
    request_id = str(envelope["request_id"])
    host_ephemeral = x25519.X25519PublicKey.from_public_bytes(
        _b64decode(str(envelope["host_ephemeral_public_key"]))
    )
    nonce = _b64decode(str(envelope["nonce"]))
    ciphertext = _b64decode(str(envelope["ciphertext"]))
    if len(ciphertext) > MAX_ENCRYPTED_PAYLOAD_BYTES + 32:
        raise ValueError("Relay response is too large")
    shared = request_key.private_key.exchange(host_ephemeral)
    key = _derive_key(shared, room_id, request_id, "response")
    decoded = ChaCha20Poly1305(key).decrypt(
        nonce,
        ciphertext,
        _aad(room_id, request_id, "response"),
    )
    payload = json.loads(decoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Relay response must decrypt to an object")
    return payload
