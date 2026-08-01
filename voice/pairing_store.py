from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import string
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    user_id: int
    guild_id: int
    device_name: str
    created_at: float
    last_seen_at: float


class PairingStore:
    def __init__(self, database_path: Path, secret_path: Path) -> None:
        self.database_path = database_path
        self.secret_path = secret_path
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = self._load_or_create_secret()
        self._initialize()

    def _load_or_create_secret(self) -> bytes:
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        if self.secret_path.exists():
            secret = self.secret_path.read_bytes()
            if len(secret) >= 32:
                return secret
        secret = secrets.token_bytes(32)
        temp = self.secret_path.with_suffix(".tmp")
        temp.write_bytes(secret)
        temp.replace(self.secret_path)
        try:
            os.chmod(self.secret_path, 0o600)
        except OSError:
            pass
        return secret

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    device_name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    revoked_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_devices_user_guild
                    ON devices(user_id, guild_id);

                CREATE TABLE IF NOT EXISTS command_receipts (
                    command_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    accepted_at REAL NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );
                """
            )

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _normalize_code(code: str) -> str:
        return "".join(character for character in code.upper() if character in PAIRING_ALPHABET)

    def create_pairing_code(self, user_id: int, guild_id: int, ttl_seconds: int = 300) -> str:
        now = time.time()
        expires = now + max(60, min(int(ttl_seconds), 900))
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM pairing_codes WHERE expires_at <= ?", (now,))
            connection.execute(
                "DELETE FROM pairing_codes WHERE user_id = ? AND guild_id = ?",
                (int(user_id), int(guild_id)),
            )
            for _ in range(10):
                code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
                try:
                    connection.execute(
                        "INSERT INTO pairing_codes(code_hash, user_id, guild_id, created_at, expires_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (self._digest(code), int(user_id), int(guild_id), now, expires),
                    )
                    return code
                except sqlite3.IntegrityError:
                    continue
        raise RuntimeError("Could not allocate a unique pairing code")

    def redeem_pairing_code(self, code: str, device_name: str) -> tuple[DeviceIdentity, str] | None:
        normalized = self._normalize_code(code)
        if len(normalized) != 8:
            return None
        now = time.time()
        code_hash = self._digest(normalized)
        clean_name = " ".join(device_name.strip().split())[:80] or "DjGoo Voice Remote"
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT user_id, guild_id, expires_at FROM pairing_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if row is None or float(row["expires_at"]) <= now:
                connection.execute("DELETE FROM pairing_codes WHERE code_hash = ?", (code_hash,))
                connection.commit()
                return None
            connection.execute("DELETE FROM pairing_codes WHERE code_hash = ?", (code_hash,))
            device_id = str(uuid.uuid4())
            token = secrets.token_urlsafe(40)
            connection.execute(
                "INSERT INTO devices(device_id, token_hash, user_id, guild_id, device_name, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    self._digest(token),
                    int(row["user_id"]),
                    int(row["guild_id"]),
                    clean_name,
                    now,
                    now,
                ),
            )
            connection.commit()
        return (
            DeviceIdentity(
                device_id=device_id,
                user_id=int(row["user_id"]),
                guild_id=int(row["guild_id"]),
                device_name=clean_name,
                created_at=now,
                last_seen_at=now,
            ),
            token,
        )

    def authenticate(self, token: str) -> DeviceIdentity | None:
        if len(token) < 32:
            return None
        token_hash = self._digest(token)
        now = time.time()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT device_id, user_id, guild_id, device_name, created_at, last_seen_at "
                "FROM devices WHERE token_hash = ? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (now, str(row["device_id"])),
            )
        return DeviceIdentity(
            device_id=str(row["device_id"]),
            user_id=int(row["user_id"]),
            guild_id=int(row["guild_id"]),
            device_name=str(row["device_name"]),
            created_at=float(row["created_at"]),
            last_seen_at=now,
        )

    def claim_command(self, command_id: str, device_id: str) -> bool:
        try:
            uuid.UUID(command_id)
        except (ValueError, AttributeError):
            return False
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM command_receipts WHERE accepted_at < ?", (now - 604800,))
            try:
                connection.execute(
                    "INSERT INTO command_receipts(command_id, device_id, accepted_at) VALUES (?, ?, ?)",
                    (command_id, device_id, now),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def list_devices(self, user_id: int, guild_id: int) -> list[DeviceIdentity]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT device_id, user_id, guild_id, device_name, created_at, last_seen_at "
                "FROM devices WHERE user_id = ? AND guild_id = ? AND revoked_at IS NULL "
                "ORDER BY last_seen_at DESC",
                (int(user_id), int(guild_id)),
            ).fetchall()
        return [
            DeviceIdentity(
                device_id=str(row["device_id"]),
                user_id=int(row["user_id"]),
                guild_id=int(row["guild_id"]),
                device_name=str(row["device_name"]),
                created_at=float(row["created_at"]),
                last_seen_at=float(row["last_seen_at"]),
            )
            for row in rows
        ]

    def revoke_device(self, device_id: str, user_id: int, guild_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE devices SET revoked_at = ? WHERE device_id = ? AND user_id = ? AND guild_id = ? "
                "AND revoked_at IS NULL",
                (time.time(), device_id, int(user_id), int(guild_id)),
            )
        return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> None:
        with self._lock, self._connect() as connection:
            device_ids = [
                str(row[0])
                for row in connection.execute("SELECT device_id FROM devices WHERE user_id = ?", (int(user_id),))
            ]
            if device_ids:
                connection.executemany(
                    "DELETE FROM command_receipts WHERE device_id = ?",
                    ((device_id,) for device_id in device_ids),
                )
            connection.execute("DELETE FROM pairing_codes WHERE user_id = ?", (int(user_id),))
            connection.execute("DELETE FROM devices WHERE user_id = ?", (int(user_id),))
