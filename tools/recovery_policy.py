from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


GRACE_SECONDS = {
    "lavalink": 20.0,
    "redbot": 75.0,
    "voice": 120.0,
}
BACKOFF_SECONDS = (2.0, 5.0, 15.0, 30.0, 60.0)
CIRCUIT_WINDOW_SECONDS = 10 * 60.0
CIRCUIT_RESTART_LIMIT = 5
CIRCUIT_OPEN_SECONDS = 5 * 60.0


@dataclass
class ComponentRecovery:
    phase: str = "Stopped"
    first_failure_at: float = 0.0
    last_failure_at: float = 0.0
    next_retry_at: float = 0.0
    circuit_open_until: float = 0.0
    consecutive_restarts: int = 0
    reason: str = ""
    restart_times: deque[float] = field(default_factory=deque)


class RecoveryPolicy:
    def __init__(self) -> None:
        self.components: dict[str, ComponentRecovery] = defaultdict(ComponentRecovery)

    def healthy(self, name: str, *, now: float | None = None) -> None:
        state = self.components[name]
        state.phase = "Ready"
        state.first_failure_at = 0.0
        state.last_failure_at = 0.0
        state.next_retry_at = 0.0
        state.reason = ""
        # A component that remains healthy long enough earns a clean backoff slate.
        current = time.monotonic() if now is None else float(now)
        self._trim_restarts(state, current)
        if not state.restart_times:
            state.consecutive_restarts = 0
            state.circuit_open_until = 0.0

    def stopped(self, name: str) -> None:
        state = self.components[name]
        state.phase = "Stopped"
        state.first_failure_at = 0.0
        state.last_failure_at = 0.0
        state.next_retry_at = 0.0
        state.reason = ""

    def observe_failure(
        self,
        name: str,
        reason: str,
        *,
        now: float | None = None,
    ) -> ComponentRecovery:
        current = time.monotonic() if now is None else float(now)
        state = self.components[name]
        if state.first_failure_at <= 0:
            state.first_failure_at = current
        state.last_failure_at = current
        state.reason = reason
        state.phase = "Degraded"
        self._trim_restarts(state, current)
        return state

    def grace_expired(self, name: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        state = self.components[name]
        if state.first_failure_at <= 0:
            return False
        return current - state.first_failure_at >= GRACE_SECONDS.get(name, 30.0)

    def can_restart(self, name: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        state = self.components[name]
        self._trim_restarts(state, current)
        if state.circuit_open_until > current:
            state.phase = "Needs attention"
            return False
        if state.next_retry_at > current:
            state.phase = "Recovering"
            return False
        return True

    def record_restart(
        self,
        name: str,
        reason: str,
        *,
        now: float | None = None,
    ) -> ComponentRecovery:
        current = time.monotonic() if now is None else float(now)
        state = self.components[name]
        self._trim_restarts(state, current)
        state.restart_times.append(current)
        state.consecutive_restarts += 1
        state.reason = reason
        if len(state.restart_times) >= CIRCUIT_RESTART_LIMIT:
            state.circuit_open_until = current + CIRCUIT_OPEN_SECONDS
            state.next_retry_at = state.circuit_open_until
            state.phase = "Needs attention"
        else:
            index = min(state.consecutive_restarts - 1, len(BACKOFF_SECONDS) - 1)
            state.next_retry_at = current + BACKOFF_SECONDS[index]
            state.phase = "Recovering"
        state.first_failure_at = 0.0
        return state

    def retry_in(self, name: str, *, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        state = self.components[name]
        return max(0.0, state.next_retry_at - current)

    def snapshot(self, name: str, *, now: float | None = None) -> dict[str, Any]:
        state = self.components[name]
        return {
            "phase": state.phase,
            "reason": state.reason,
            "retry_in_seconds": round(self.retry_in(name, now=now), 1),
            "consecutive_restarts": state.consecutive_restarts,
            "circuit_open": state.circuit_open_until
            > (time.monotonic() if now is None else float(now)),
        }

    def _trim_restarts(self, state: ComponentRecovery, now: float) -> None:
        while state.restart_times and now - state.restart_times[0] > CIRCUIT_WINDOW_SECONDS:
            state.restart_times.popleft()
        if not state.restart_times and state.next_retry_at <= now:
            state.consecutive_restarts = 0


def install_recovery_policy(core: Any) -> RecoveryPolicy:
    """Replace immediate steady-state restarts with bounded recovery behavior."""

    policy = RecoveryPolicy()
    original_update_component_status = core.update_component_status
    original_stop_stack = core.stop_stack

    def update_component_status(specs: list[Any]) -> None:
        original_update_component_status(specs)
        with core.STATE.lock:
            for spec in specs:
                current = core.STATE.component_status.setdefault(spec.name, {})
                current.update(policy.snapshot(spec.name))
        core.persist_state()

    def stop_stack(specs: list[Any], reason: str) -> None:
        original_stop_stack(specs, reason)
        for spec in specs:
            policy.stopped(spec.name)
        update_component_status(specs)

    def ensure_stack(
        specs: list[Any],
        *,
        resume_playback: bool = False,
    ) -> None:
        if not core.discord_network_ready():
            with core.STATE.lock:
                core.STATE.last_error = "Discord network is unavailable"
            core.LOG.event("network.not_ready")
            core.persist_state()
            return

        for spec in specs:
            with core.STATE.lock:
                if not core.STATE.desired_running or core.STATE.shutdown_requested:
                    return

            running = core.component_running(spec)
            ready = bool(running and spec.ready())
            if ready:
                policy.healthy(spec.name)
                continue

            if running:
                state = policy.observe_failure(
                    spec.name,
                    "readiness predicate failed",
                )
                if not policy.grace_expired(spec.name):
                    core.LOG.event(
                        "component.degraded",
                        component=spec.name,
                        grace_seconds=GRACE_SECONDS.get(spec.name, 30.0),
                        reason=state.reason,
                    )
                    with core.STATE.lock:
                        core.STATE.last_error = ""
                    update_component_status(specs)
                    return

            if not policy.can_restart(spec.name):
                retry = policy.retry_in(spec.name)
                with core.STATE.lock:
                    core.STATE.last_error = (
                        f"{spec.name} recovery paused for {round(retry)} seconds"
                        if retry > 0
                        else f"{spec.name} needs attention"
                    )
                update_component_status(specs)
                return

            if running:
                core.terminate_component(spec, "continuous-readiness-failure")

            recovery_resume = resume_playback or spec.name == "redbot"
            if not core.start_component(
                spec,
                resume_playback=recovery_resume,
            ):
                policy.record_restart(spec.name, "start failed")
                with core.STATE.lock:
                    core.STATE.last_error = f"Could not start {spec.name}"
                update_component_status(specs)
                return

            if not core.wait_until_ready(spec):
                core.terminate_component(spec, "readiness-failed")
                policy.record_restart(spec.name, "readiness timeout")
                with core.STATE.lock:
                    core.STATE.last_error = f"{spec.name} did not become ready"
                update_component_status(specs)
                return

            policy.record_restart(spec.name, "automatic recovery")
            policy.healthy(spec.name)

        with core.STATE.lock:
            core.STATE.last_error = ""
        update_component_status(specs)

    core.update_component_status = update_component_status
    core.stop_stack = stop_stack
    core.ensure_stack = ensure_stack
    core._djgoo_recovery_policy = policy
    return policy
