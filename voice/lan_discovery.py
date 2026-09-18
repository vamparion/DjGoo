from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import secrets
import socket
import time
from collections.abc import Callable

from voice.network_routes import local_ipv4_addresses


DISCOVERY_PORT = 49179
DISCOVERY_MULTICAST_GROUP = "239.255.71.71"
REQUEST_TYPE = "DJGOO-DISCOVER-1"
RESPONSE_TYPE = "DJGOO-OFFER-1"
MAX_PACKET_BYTES = 2048
DEFAULT_TIMEOUT_SECONDS = 1.6


def normalize_fingerprint(value: str) -> str:
    return "".join(
        character
        for character in str(value).lower()
        if character in "0123456789abcdef"
    )


def _encode_packet(payload: dict[str, object]) -> bytes:
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    if len(encoded) > MAX_PACKET_BYTES:
        raise ValueError("DjGoo LAN discovery packet is too large")
    return encoded


def _decode_packet(data: bytes) -> dict[str, object]:
    if not data or len(data) > MAX_PACKET_BYTES:
        raise ValueError("DjGoo LAN discovery packet has an invalid size")
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("DjGoo LAN discovery packet is invalid")
    return payload


class LanDiscoveryProtocol(asyncio.DatagramProtocol):
    """Answer recipient discovery from the interface that received the request."""

    def __init__(
        self,
        *,
        gateway_port: int,
        fingerprint: str,
        host_name: str = "DjGoo Host",
        log: Callable[[str], None] | None = None,
    ) -> None:
        normalized = normalize_fingerprint(fingerprint)
        if len(normalized) != 64:
            raise ValueError("DjGoo LAN discovery requires a TLS fingerprint")
        self.gateway_port = int(gateway_port)
        self.fingerprint = normalized
        self.host_name = " ".join(str(host_name).split())[:80] or "DjGoo Host"
        self.log = log or (lambda _message: None)
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, address) -> None:
        try:
            payload = _decode_packet(data)
            if str(payload.get("type") or "") != REQUEST_TYPE:
                return
            nonce = str(payload.get("nonce") or "").strip()
            expected = normalize_fingerprint(
                str(payload.get("fingerprint") or "")
            )
            if not (16 <= len(nonce) <= 128):
                return
            if expected != self.fingerprint:
                return
            response = _encode_packet(
                {
                    "type": RESPONSE_TYPE,
                    "nonce": nonce,
                    "port": self.gateway_port,
                    "fingerprint": self.fingerprint,
                    "host_name": self.host_name,
                }
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if self.transport is not None:
            self.transport.sendto(response, address)

    def error_received(self, exc: Exception) -> None:
        self.log(f"LAN discovery socket error: {exc}")


class LanDiscoveryResponder:
    def __init__(
        self,
        *,
        gateway_port: int,
        fingerprint: str,
        host_name: str = "DjGoo Host",
        listen_port: int = DISCOVERY_PORT,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.gateway_port = int(gateway_port)
        self.fingerprint = fingerprint
        self.host_name = host_name
        self.listen_port = int(listen_port)
        self.log = log
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: LanDiscoveryProtocol | None = None

    def _socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", self.listen_port))
        interfaces = ["0.0.0.0", *local_ipv4_addresses()]
        for interface in dict.fromkeys(interfaces):
            membership = (
                socket.inet_aton(DISCOVERY_MULTICAST_GROUP)
                + socket.inet_aton(interface)
            )
            with contextlib.suppress(OSError):
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_ADD_MEMBERSHIP,
                    membership,
                )
        sock.setblocking(False)
        return sock

    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        sock = self._socket()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: LanDiscoveryProtocol(
                    gateway_port=self.gateway_port,
                    fingerprint=self.fingerprint,
                    host_name=self.host_name,
                    log=self.log,
                ),
                sock=sock,
            )
        except BaseException:
            sock.close()
            raise
        self._transport = transport
        self._protocol = protocol

    async def stop(self) -> None:
        if self._transport is None:
            return
        self._transport.close()
        self._transport = None
        self._protocol = None
        await asyncio.sleep(0)


def _broadcast_targets(port: int) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = [
        (DISCOVERY_MULTICAST_GROUP, int(port)),
        ("255.255.255.255", int(port)),
    ]
    for address in local_ipv4_addresses():
        try:
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        except ValueError:
            continue
        target = (str(network.broadcast_address), int(port))
        if target not in targets:
            targets.append(target)
    return targets


def _discover_gateway_urls(
    expected_fingerprint: str,
    *,
    discovery_port: int,
    timeout_seconds: float,
) -> list[str]:
    fingerprint = normalize_fingerprint(expected_fingerprint)
    if len(fingerprint) != 64:
        return []
    nonce = secrets.token_urlsafe(24)
    request = _encode_packet(
        {
            "type": REQUEST_TYPE,
            "nonce": nonce,
            "fingerprint": fingerprint,
        }
    )
    discovered: list[str] = []
    deadline = time.monotonic() + max(0.2, float(timeout_seconds))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.bind(("", 0))
        for _attempt in range(2):
            for target in _broadcast_targets(discovery_port):
                try:
                    sock.sendto(request, target)
                except OSError:
                    continue
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            sock.settimeout(min(0.2, remaining))
            try:
                data, source = sock.recvfrom(MAX_PACKET_BYTES)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = _decode_packet(data)
                if str(payload.get("type") or "") != RESPONSE_TYPE:
                    continue
                if str(payload.get("nonce") or "") != nonce:
                    continue
                returned_fingerprint = normalize_fingerprint(
                    str(payload.get("fingerprint") or "")
                )
                if returned_fingerprint != fingerprint:
                    continue
                port = int(payload.get("port") or 0)
                if not (1 <= port <= 65535):
                    continue
                address = str(source[0])
                ip = ipaddress.ip_address(address)
                if ip.version != 4 or ip.is_unspecified or ip.is_loopback:
                    continue
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            url = f"https://{address}:{port}"
            if url not in discovered:
                discovered.append(url)
    finally:
        sock.close()
    return discovered


async def discover_gateway_urls(
    expected_fingerprint: str,
    *,
    discovery_port: int = DISCOVERY_PORT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Discover certificate-pinned DjGoo Hosts on the recipient's current LAN."""

    return await asyncio.to_thread(
        _discover_gateway_urls,
        expected_fingerprint,
        discovery_port=int(discovery_port),
        timeout_seconds=float(timeout_seconds),
    )
