from __future__ import annotations

import ipaddress
import socket
from typing import Iterable


def _candidate_addresses() -> Iterable[str]:
    # The UDP socket chooses the interface Windows would use for normal outbound
    # traffic without sending a packet. This is more reliable than hostname DNS
    # on systems with VPN, ASTER, Hyper-V, or stale virtual adapters.
    for destination in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(destination)
            yield str(sock.getsockname()[0])
        except OSError:
            pass
        finally:
            sock.close()

    try:
        for entry in socket.getaddrinfo(
            socket.gethostname(),
            None,
            socket.AF_INET,
            socket.SOCK_STREAM,
        ):
            yield str(entry[4][0])
    except OSError:
        pass


def lan_addresses() -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for value in _candidate_addresses():
        if value in seen:
            continue
        seen.add(value)
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address):
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            continue
        if address.is_private:
            rank = 0
        elif address.is_link_local:
            rank = 2
        else:
            rank = 1
        ranked.append((rank, value))
    return [value for _rank, value in sorted(ranked)]


def best_lan_address(default: str = "127.0.0.1") -> str:
    addresses = lan_addresses()
    return addresses[0] if addresses else default
