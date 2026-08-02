from __future__ import annotations

import secrets
import sqlite3
import time

from voice.pairing_store import PAIRING_ALPHABET, PairingStore


def _create_route_safe_pairing_code(
    self: PairingStore,
    user_id: int,
    guild_id: int,
    ttl_seconds: int = 300,
) -> str:
    """Create an independent short-lived route code without revoking siblings.

    A DjGoo Link invitation can contain Discord, hosted-relay, and multiple direct
    routes. Each route has its own code. The former implementation deleted every
    existing code for the same user and guild before inserting the next one, so
    building a multi-route invitation invalidated its earlier routes before the
    DM was sent. Expired codes are still removed and every code remains single-use.
    """

    now = time.time()
    expires = now + max(60, min(int(ttl_seconds), 900))
    with self._lock, self._connect() as connection:
        connection.execute("DELETE FROM pairing_codes WHERE expires_at <= ?", (now,))
        for _ in range(10):
            code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
            try:
                connection.execute(
                    "INSERT INTO pairing_codes(code_hash, user_id, guild_id, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        self._digest(code),
                        int(user_id),
                        int(guild_id),
                        now,
                        expires,
                    ),
                )
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("Could not allocate a unique pairing code")


def install_route_safe_pairing_codes() -> None:
    """Install the multi-route-safe code allocator once per process."""

    if bool(getattr(PairingStore, "_djgoo_route_safe_codes", False)):
        return
    PairingStore.create_pairing_code = _create_route_safe_pairing_code
    PairingStore._djgoo_route_safe_codes = True
