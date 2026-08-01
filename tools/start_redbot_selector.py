from __future__ import annotations

import asyncio
import runpy
import socket
import sys
from pathlib import Path
from typing import BinaryIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTANCE_NAME = "discordbot"
STARTUP_COGS = ("audio", "djgoowelcome")
INSTANCE_LOCK = PROJECT_ROOT / "data" / "redbot-instance.lock"


class SingleInstance:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.handle.close()
            self.handle = None
            return False
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


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


def duplicate_instance_message(project_root: Path = PROJECT_ROOT) -> str:
    return (
        "Another DjGoo Redbot process is already using this package.\n"
        "Stop DjGoo before opening the bot console. Starting a second copy would "
        "conflict with Redbot's latest.log file.\n"
        f"Current Redbot log: {project_root / 'data' / INSTANCE_NAME / 'core' / 'logs' / 'latest.log'}"
    )


def main() -> int:
    instance = SingleInstance(INSTANCE_LOCK)
    if not instance.acquire():
        print(duplicate_instance_message(PROJECT_ROOT), file=sys.stderr)
        return 2
    try:
        apply_runtime_patches()
        sys.argv = redbot_argv(PROJECT_ROOT)
        runpy.run_module("redbot", run_name="__main__")
        return 0
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
