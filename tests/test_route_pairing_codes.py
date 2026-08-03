from __future__ import annotations

from voice.pairing_code_routes import install_route_safe_pairing_codes
from voice.pairing_store import PairingStore


def test_multi_route_invite_codes_remain_valid_until_each_is_redeemed(tmp_path) -> None:
    install_route_safe_pairing_codes()
    store = PairingStore(
        tmp_path / "pairing.sqlite3",
        tmp_path / "pairing-secret.key",
    )

    codes = [
        store.create_pairing_code(123, 456, 300)
        for _ in range(3)
    ]

    assert len(set(codes)) == 3
    redeemed = [
        store.redeem_pairing_code(code, f"Route {index}")
        for index, code in enumerate(codes)
    ]
    assert all(result is not None for result in redeemed)
    assert len({result[0].device_id for result in redeemed if result is not None}) == 3

    # Every route code remains single-use even though sibling route codes coexist.
    assert all(
        store.redeem_pairing_code(code, "Duplicate") is None
        for code in codes
    )


def test_new_route_code_does_not_revoke_an_existing_short_lived_code(tmp_path) -> None:
    install_route_safe_pairing_codes()
    store = PairingStore(
        tmp_path / "pairing.sqlite3",
        tmp_path / "pairing-secret.key",
    )

    first = store.create_pairing_code(123, 456, 300)
    second = store.create_pairing_code(123, 456, 300)

    assert store.redeem_pairing_code(first, "Discord route") is not None
    assert store.redeem_pairing_code(second, "Direct route") is not None
