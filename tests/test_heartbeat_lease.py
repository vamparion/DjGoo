from __future__ import annotations

import json
from pathlib import Path

from voice import health


def test_heartbeat_write_retries_windows_sharing_violation(tmp_path, monkeypatch) -> None:
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated Windows sharing violation")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    health._write_payload("redbot", project_root=tmp_path, fields={"ready": True})

    payload = json.loads(
        health.heartbeat_path("redbot", tmp_path).read_text(encoding="utf-8")
    )
    assert payload["ready"] is True
    assert attempts == 3


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


def test_redbot_lease_changes_ready_event_to_runtime_lease() -> None:
    fields = health._leased_fields(
        "redbot",
        {"fields": {"event": "redbot.ready", "ready": True}},
        12.5,
    )

    assert fields["event"] == "redbot.lease"
    assert fields["heartbeat_source_event"] == "redbot.ready"
    assert fields["heartbeat_source_age_seconds"] == 12.5
