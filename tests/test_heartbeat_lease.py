from __future__ import annotations

from voice import health


def test_redbot_lease_bridges_a_long_command() -> None:
    assert health._lease_is_active(
        "redbot",
        source_monotonic=100.0,
        now_monotonic=145.0,
    )


def test_redbot_lease_expires_instead_of_hiding_a_dead_process() -> None:
    assert not health._lease_is_active(
        "redbot",
        source_monotonic=100.0,
        now_monotonic=161.0,
    )


def test_lavalink_client_uses_a_shorter_lease() -> None:
    assert health._lease_is_active(
        "lavalink-client",
        source_monotonic=100.0,
        now_monotonic=119.0,
    )
    assert not health._lease_is_active(
        "lavalink-client",
        source_monotonic=100.0,
        now_monotonic=121.0,
    )
