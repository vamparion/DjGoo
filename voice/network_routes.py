from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


def _usable_private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.version == 4
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
    )


def local_ipv4_addresses() -> list[str]:
    """Return deterministic private IPv4 addresses for the current Host."""

    discovered: list[str] = []

    # The routing table usually provides the best address even when hostname
    # resolution is stale or resolves to an ASTER/virtual adapter first.
    for target in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(target)
            discovered.append(str(sock.getsockname()[0]))
        except OSError:
            pass
        finally:
            sock.close()

    try:
        discovered.extend(
            str(entry[4][0])
            for entry in socket.getaddrinfo(
                socket.gethostname(),
                None,
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
        )
    except OSError:
        pass

    result: list[str] = []
    for address in discovered:
        if _usable_private_ipv4(address) and address not in result:
            result.append(address)
    return result


def gateway_urls(
    *,
    port: int,
    configured_url: str = "",
) -> list[str]:
    """Build public/configured and every usable LAN gateway URL."""

    result: list[str] = []
    configured = configured_url.strip().rstrip("/")
    if configured:
        parsed = urlsplit(configured)
        if parsed.scheme.lower() == "https" and parsed.netloc:
            result.append(configured)

    for address in local_ipv4_addresses():
        candidate = f"https://{address}:{int(port)}"
        if candidate not in result:
            result.append(candidate)
    return result
