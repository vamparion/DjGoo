from __future__ import annotations

from voice.lan_discovery import (
    REQUEST_TYPE,
    RESPONSE_TYPE,
    LanDiscoveryProtocol,
    _decode_packet,
    _encode_packet,
)


class _Transport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, address) -> None:
        self.sent.append((data, address))


def test_discovery_response_preserves_nonce_and_pinned_identity() -> None:
    fingerprint = "a" * 64
    protocol = LanDiscoveryProtocol(
        gateway_port=47632,
        fingerprint=fingerprint,
    )
    transport = _Transport()
    protocol.connection_made(transport)

    protocol.datagram_received(
        _encode_packet(
            {
                "type": REQUEST_TYPE,
                "nonce": "recipient-nonce-123456",
                "fingerprint": fingerprint,
            }
        ),
        ("192.168.8.200", 54000),
    )

    assert len(transport.sent) == 1
    packet, address = transport.sent[0]
    payload = _decode_packet(packet)
    assert address == ("192.168.8.200", 54000)
    assert payload["type"] == RESPONSE_TYPE
    assert payload["nonce"] == "recipient-nonce-123456"
    assert payload["port"] == 47632
    assert payload["fingerprint"] == fingerprint


def test_discovery_ignores_requests_for_a_different_host() -> None:
    protocol = LanDiscoveryProtocol(
        gateway_port=47632,
        fingerprint="a" * 64,
    )
    transport = _Transport()
    protocol.connection_made(transport)

    protocol.datagram_received(
        _encode_packet(
            {
                "type": REQUEST_TYPE,
                "nonce": "recipient-nonce-123456",
                "fingerprint": "b" * 64,
            }
        ),
        ("192.168.8.200", 54000),
    )

    assert transport.sent == []
