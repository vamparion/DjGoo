from __future__ import annotations

import asyncio
import runpy
import socket
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.portable_environment import apply_portable_environment


INSTANCE_NAME = "discordbot"
STARTUP_COGS = ("audio", "djgoowelcome")
CONSOLE_FLAG = "--djgoo-console"


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


def apply_runtime_patches() -> None:
    socket.socketpair = _ipv6_socketpair
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from redbot.cogs.audio.managed_node import ll_server_config

    ll_server_config.DEFAULT_LAVALINK_YAML["yaml__server__address"] = "::1"


def redbot_argv(project_root: Path = PROJECT_ROOT) -> list[str]:
    local_cogs = (project_root / "local_cogs").resolve()
    return [
        "redbot",
        INSTANCE_NAME,
        "--cog-path",
        str(local_cogs),
        "--load-cogs",
        *STARTUP_COGS,
    ]


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _pause_after_error() -> None:
    print("\nDjGoo could not keep Redbot running.")
    print("The error above has been left visible so it can be diagnosed.")
    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass


def run_redbot(project_root: Path = PROJECT_ROOT) -> None:
    apply_portable_environment(project_root)
    apply_runtime_patches()
    sys.argv = redbot_argv(project_root)
    runpy.run_module("redbot", run_name="__main__")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    console_mode = CONSOLE_FLAG in arguments
    try:
        run_redbot(PROJECT_ROOT)
    except SystemExit as exc:
        code = _exit_code(exc.code)
        if console_mode and code != 0:
            _pause_after_error()
        return code
    except BaseException:
        traceback.print_exc()
        if console_mode:
            _pause_after_error()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
