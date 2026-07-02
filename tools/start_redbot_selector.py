import asyncio
import runpy
import socket
import sys
from pathlib import Path


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
