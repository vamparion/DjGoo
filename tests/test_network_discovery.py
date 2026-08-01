from __future__ import annotations

from voice import network_discovery


def test_private_lan_address_is_preferred(monkeypatch) -> None:
    monkeypatch.setattr(
        network_discovery,
        "_candidate_addresses",
        lambda: iter(
            [
                "127.0.0.1",
                "169.254.10.20",
                "192.168.8.25",
                "8.8.8.8",
            ]
        ),
    )

    assert network_discovery.lan_addresses()[0] == "192.168.8.25"
    assert network_discovery.best_lan_address() == "192.168.8.25"


def test_loopback_is_only_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        network_discovery,
        "_candidate_addresses",
        lambda: iter(["127.0.0.1", "0.0.0.0"]),
    )

    assert network_discovery.lan_addresses() == []
    assert network_discovery.best_lan_address() == "127.0.0.1"
