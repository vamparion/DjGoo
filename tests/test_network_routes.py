from __future__ import annotations

from voice import network_routes


def test_private_route_filter_rejects_loopback_and_public_addresses() -> None:
    assert network_routes._usable_private_ipv4("192.168.8.128") is True
    assert network_routes._usable_private_ipv4("10.0.0.5") is True
    assert network_routes._usable_private_ipv4("127.0.0.1") is False
    assert network_routes._usable_private_ipv4("8.8.8.8") is False
    assert network_routes._usable_private_ipv4("169.254.1.2") is False


def test_gateway_urls_keep_public_route_and_all_lan_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        network_routes,
        "local_ipv4_addresses",
        lambda: ["192.168.8.128", "10.20.30.40"],
    )

    assert network_routes.gateway_urls(
        port=47632,
        configured_url="https://djgoo.example.test",
    ) == [
        "https://djgoo.example.test",
        "https://192.168.8.128:47632",
        "https://10.20.30.40:47632",
    ]
