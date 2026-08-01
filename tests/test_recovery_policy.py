from __future__ import annotations

from tools.recovery_policy import (
    CIRCUIT_OPEN_SECONDS,
    CIRCUIT_RESTART_LIMIT,
    RecoveryPolicy,
)


def test_failure_must_outlive_grace() -> None:
    policy = RecoveryPolicy()
    policy.observe_failure("redbot", "heartbeat", now=100.0)

    assert policy.snapshot("redbot", now=110.0)["phase"] == "Degraded"
    assert policy.grace_expired("redbot", now=150.0) is False
    assert policy.grace_expired("redbot", now=176.0) is True


def test_restarts_back_off_progressively() -> None:
    policy = RecoveryPolicy()

    first = policy.record_restart("redbot", "failed", now=100.0)
    assert first.next_retry_at == 102.0
    assert policy.can_restart("redbot", now=101.0) is False
    assert policy.can_restart("redbot", now=102.0) is True

    second = policy.record_restart("redbot", "failed", now=102.0)
    assert second.next_retry_at == 107.0


def test_circuit_breaker_opens_after_repeated_restarts() -> None:
    policy = RecoveryPolicy()
    for index in range(CIRCUIT_RESTART_LIMIT):
        state = policy.record_restart(
            "voice",
            "crashed",
            now=100.0 + index,
        )

    assert state.phase == "Needs attention"
    assert state.circuit_open_until == 100.0 + CIRCUIT_RESTART_LIMIT - 1 + CIRCUIT_OPEN_SECONDS
    assert policy.can_restart("voice", now=200.0) is False


def test_intentional_stop_clears_backoff_history() -> None:
    policy = RecoveryPolicy()
    policy.record_restart("lavalink", "failed", now=100.0)

    policy.stopped("lavalink")

    snapshot = policy.snapshot("lavalink", now=101.0)
    assert snapshot["phase"] == "Stopped"
    assert snapshot["consecutive_restarts"] == 0
    assert snapshot["retry_in_seconds"] == 0
