import asyncio
import runpy
import socket
import sys
from contextlib import closing
from pathlib import Path

_original_getaddrinfo = socket.getaddrinfo

_DISCORD_FALLBACK_IPV4 = {
    "discord.com": ("162.159.135.232", "162.159.136.232", "162.159.137.232", "162.159.138.232"),
    "gateway.discord.gg": (
        "162.159.130.234",
        "162.159.133.234",
        "162.159.134.234",
        "162.159.135.234",
        "162.159.136.234",
    ),
}


def _discord_fallback_ips(host: object) -> tuple[str, ...]:
    hostname = str(host).strip(".").lower()
    if hostname in _DISCORD_FALLBACK_IPV4:
        return _DISCORD_FALLBACK_IPV4[hostname]
    if hostname.endswith(".discord.gg"):
        return _DISCORD_FALLBACK_IPV4["gateway.discord.gg"]
    return ()


def _resilient_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        fallback_ips = _discord_fallback_ips(host)
        if not fallback_ips:
            raise
        results = []
        for ip_address in fallback_ips:
            try:
                with closing(socket.create_connection((ip_address, port), timeout=1.5)):
                    pass
            except OSError:
                continue
            results.extend(_original_getaddrinfo(ip_address, port, socket.AF_INET, type, proto, flags))
        if not results:
            raise
        return results


def _ipv6_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
    if family not in (socket.AF_INET, socket.AF_INET6):
        raise ValueError("Only AF_INET and AF_INET6 socket pairs are supported")
    listener = socket.socket(socket.AF_INET6, type, proto)
    listener.bind(("::1", 0))
    listener.listen(1)
    client = socket.socket(socket.AF_INET6, type, proto)
    try:
        client.connect(listener.getsockname())
        server, _ = listener.accept()
    except BaseException:
        client.close()
        raise
    finally:
        listener.close()
    return client, server


socket.getaddrinfo = _resilient_getaddrinfo
socket.socketpair = _ipv6_socketpair

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from redbot.cogs.audio.managed_node import ll_server_config

ll_server_config.DEFAULT_LAVALINK_YAML["yaml__server__address"] = "::1"

def main() -> None:
    sys.argv = [
        "redbot",
        "discordbot",
        "--cog-path",
        str(Path("local_cogs").resolve()),
        "--load-cogs",
        "audio",
        "djgoowelcome",
    ]
    runpy.run_module("redbot", run_name="__main__")


if __name__ == "__main__":
    main()
