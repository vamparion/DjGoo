from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from tools.recovery_policy import (
    CIRCUIT_OPEN_SECONDS,
    CIRCUIT_RESTART_LIMIT,
    RecoveryPolicy,
    install_recovery_policy,
)


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **fields: object) -> None:
        self.events.append((name, fields))


class FakeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.desired_running = True
        self.shutdown_requested = False
        self.last_error = ""
        self.component_status: dict[str, dict[str, object]] = {}


def make_fake_core(tmp_path: Path) -> SimpleNamespace:
    logger = RecordingLogger()
    state = FakeState()
    core = SimpleNamespace()
    core.PROJECT_ROOT = tmp_path
    core.STATE = state
    core.LOG = logger
    core.discord_network_ready = lambda: True
    core.component_running = lambda spec: False
    core.terminate_component = lambda spec, reason: None
    core.start_component = lambda spec, *, resume_playback=False: True
    core.wait_until_ready = lambda spec: False
    core.health_path = lambda name: tmp_path / "health" / f"{name}.json"
    core.read_json = lambda path: None
    core.persist_state = lambda: None
    core.update_component_status = lambda specs: None
    core.stop_stack = lambda specs, reason: None
    core._events = logger.events
    return core


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


def test_redbot_setup_required_stops_recovery_retries(tmp_path) -> None:
    core = make_fake_core(tmp_path)
    settings = tmp_path / "data" / "discordbot" / "core" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n", encoding="utf-8")
    core.read_json = lambda path: {
        "ready": False,
        "setup_required": True,
        "message": "Music Core setup is required",
    }
    starts: list[str] = []
    core.start_component = (
        lambda spec, *, resume_playback=False: starts.append(spec.name) or True
    )
    policy = install_recovery_policy(core)
    spec = SimpleNamespace(name="redbot", ready=lambda: False)

    core.ensure_stack([spec])

    assert starts == []
    assert core.STATE.last_error == "Music Core setup is required"
    assert policy.snapshot("redbot")["phase"] == "Needs attention"
    assert any(name == "component.needs_attention" for name, _ in core._events)


def test_redbot_setup_required_is_checked_before_readiness_cleanup(tmp_path) -> None:
    core = make_fake_core(tmp_path)
    settings = tmp_path / "data" / "discordbot" / "core" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n", encoding="utf-8")
    heartbeat: dict[str, object] | None = {
        "ready": False,
        "setup_required": True,
        "message": "Music Core setup is required",
    }
    core.read_json = lambda path: heartbeat
    core.component_running = lambda spec: False

    def delete_heartbeat(spec, reason):
        nonlocal heartbeat
        heartbeat = None

    core.terminate_component = delete_heartbeat
    install_recovery_policy(core)
    spec = SimpleNamespace(name="redbot", ready=lambda: False)

    core.ensure_stack([spec])

    assert heartbeat is not None
    assert core.STATE.last_error == "Music Core setup is required"


def test_configured_music_core_ignores_stale_setup_required_heartbeat(tmp_path) -> None:
    core = make_fake_core(tmp_path)
    settings = tmp_path / "data" / "discordbot" / "core" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"token": "configured"}\n', encoding="utf-8")
    core.read_json = lambda path: {
        "ready": False,
        "setup_required": True,
        "message": "Music Core setup is required",
    }
    starts: list[str] = []
    core.start_component = (
        lambda spec, *, resume_playback=False: starts.append(spec.name) or True
    )
    install_recovery_policy(core)
    spec = SimpleNamespace(name="redbot", ready=lambda: False)

    core.ensure_stack([spec])

    assert starts == ["redbot"]
    assert core.STATE.last_error == "redbot did not become ready"


def test_redbot_fatal_heartbeat_stops_recovery_retries(tmp_path) -> None:
    core = make_fake_core(tmp_path)
    settings = tmp_path / "data" / "discordbot" / "core" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"configured": true}\n', encoding="utf-8")
    core.read_json = lambda path: {
        "ready": False,
        "fatal": True,
        "reason": "invalid-discord-token",
        "message": "Discord rejected DjGoo's bot token.",
    }
    starts: list[str] = []
    core.start_component = (
        lambda spec, *, resume_playback=False: starts.append(spec.name) or True
    )
    policy = install_recovery_policy(core)
    spec = SimpleNamespace(name="redbot", ready=lambda: False)

    core.ensure_stack([spec])

    assert starts == []
    assert core.STATE.last_error == "Discord rejected DjGoo's bot token."
    assert policy.snapshot("redbot")["phase"] == "Needs attention"
