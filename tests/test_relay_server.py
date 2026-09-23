from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from relay.server import SlidingWindowLimiter, client_rate_key


def test_relay_rate_key_uses_forwarded_client_only_when_proxy_is_trusted(monkeypatch) -> None:
    request = SimpleNamespace(
        headers={"X-Forwarded-For": "203.0.113.41, 10.0.0.4"},
        remote="127.0.0.1",
    )

    monkeypatch.delenv("DJGOO_RELAY_TRUST_PROXY", raising=False)
    assert client_rate_key(request) == "127.0.0.1"

    monkeypatch.setenv("DJGOO_RELAY_TRUST_PROXY", "1")
    assert client_rate_key(request) == "203.0.113.41"


def test_relay_rate_key_prefers_valid_cloudflare_client_ip(monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_RELAY_TRUST_PROXY", "1")
    request = SimpleNamespace(
        headers={
            "CF-Connecting-IP": "2001:db8::7",
            "X-Forwarded-For": "203.0.113.41, 10.0.0.4",
        },
        remote="127.0.0.1",
    )

    assert client_rate_key(request) == "2001:db8::7"


def test_relay_rate_key_rejects_spoofed_invalid_forwarded_value(monkeypatch) -> None:
    monkeypatch.setenv("DJGOO_RELAY_TRUST_PROXY", "1")
    request = SimpleNamespace(
        headers={"X-Forwarded-For": "not-an-ip"},
        remote="192.0.2.8",
    )

    assert client_rate_key(request) == "192.0.2.8"


def test_sliding_window_limiter_prunes_expired_keys(monkeypatch) -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10)
    limiter._events["stale"].append(1.0)
    limiter._last_prune = 100.0
    monkeypatch.setattr("relay.server.time.monotonic", lambda: 111.0)

    assert limiter.allow("current") is True
    assert "stale" not in limiter._events


def test_hosted_relay_compose_paths_resolve_from_relay_directory() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "relay" / "compose.yml").read_text(encoding="utf-8")

    assert "context: .." in compose
    assert "dockerfile: relay/Dockerfile" in compose
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in compose
