from __future__ import annotations

import asyncio
import json
import runpy
import socket
import sys
import traceback
from pathlib import Path
from typing import Any, BinaryIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.lavalink_process import cleanup_lavalink_processes
from tools.portable_environment import bind_red_data_manager, red_config_dir
from tools.portable_red_setup import ensure_instance, verify_red_instance_runtime


INSTANCE_NAME = "discordbot"
STARTUP_COGS = ("audio", "djgoowelcome")
CONSOLE_FLAG = "--djgoo-console"
CHECK_FLAG = "--djgoo-check"
DUPLICATE_EXIT_CODE = 75


class RedbotAlreadyRunning(RuntimeError):
    pass


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


def redbot_lock_path(project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "data" / "redbot-instance.lock"


def duplicate_instance_message(project_root: Path = PROJECT_ROOT) -> str:
    return (
        "Another DjGoo Redbot process is already using this package.\n"
        "Stop DjGoo before opening the bot console. Starting a second copy would "
        "conflict with Redbot's latest.log file.\n"
        f"Current Redbot log: {project_root / 'data' / INSTANCE_NAME / 'core' / 'logs' / 'latest.log'}"
    )


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


async def configure_managed_lavalink(cog: Any) -> None:
    """Return Red Audio to its native managed Lavalink lifecycle.

    Older DjGoo alpha builds persisted external-node mode while also launching
    Lavalink from the supervisor. Force that setting off before Audio performs
    its normal initialization so Red owns the Java node exactly as it did in the
    originally working setup.
    """

    await cog.config.use_external_lavalink.set(False)


def install_audio_runtime_patch(audio_package: Any) -> None:
    """Force managed-node mode before Red Audio initializes."""

    audio_class = audio_package.Audio
    if bool(getattr(audio_class, "_djgoo_managed_lavalink_patch", False)):
        return

    original_initialize = audio_class.initialize

    async def djgoo_initialize(self: Any) -> None:
        await configure_managed_lavalink(self)
        await original_initialize(self)

    audio_class.initialize = djgoo_initialize
    audio_class._djgoo_managed_lavalink_patch = True
    audio_class._djgoo_original_initialize = original_initialize


def apply_runtime_patches() -> None:
    socket.socketpair = _ipv6_socketpair
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import redbot.cogs.audio as audio_package

    install_audio_runtime_patch(audio_package)


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


def check_portable_red(project_root: Path = PROJECT_ROOT) -> None:
    """Repair and exercise DjGoo's real portable Red instance."""

    prepared = ensure_instance(project_root)
    actual = bind_red_data_manager(project_root).resolve()
    expected = (red_config_dir(project_root) / "config.json").resolve()
    if actual != expected or prepared.resolve() != expected:
        raise RuntimeError(
            "Red configuration path mismatch. "
            f"DjGoo prepared {prepared.resolve()}, but Red resolved {actual}."
        )
    try:
        payload = json.loads(actual.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Portable Red configuration is missing: {actual}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Portable Red configuration is invalid JSON: {actual}") from exc
    if not isinstance(payload, dict) or INSTANCE_NAME not in payload:
        raise RuntimeError(f"Red instance '{INSTANCE_NAME}' is missing from {actual}")

    instance = payload[INSTANCE_NAME]
    if not isinstance(instance, dict):
        raise RuntimeError(f"Red instance '{INSTANCE_NAME}' is not an object in {actual}")
    for key in ("COG_PATH_APPEND", "CORE_PATH_APPEND"):
        value = instance.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Red instance field {key} must be a non-empty string in {actual}")

    core_path, cog_path = verify_red_instance_runtime(project_root)

    import pip

    print(f"DjGoo portable Red configuration OK: {actual}")
    print(f"Red core data path OK: {core_path}")
    print(f"Red cog data path OK: {cog_path}")
    print("Red core JSON driver initialization OK")
    print(f"Bundled pip import OK: {pip.__version__}")


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
    instance = SingleInstance(redbot_lock_path(project_root))
    if not instance.acquire():
        raise RedbotAlreadyRunning(duplicate_instance_message(project_root))
    try:
        # Always migrate early portable configurations before Red reads them.
        ensure_instance(project_root)
        bind_red_data_manager(project_root)
        cleanup_lavalink_processes(project_root)
        apply_runtime_patches()
        sys.argv = redbot_argv(project_root)
        runpy.run_module("redbot", run_name="__main__")
    finally:
        instance.close()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    console_mode = CONSOLE_FLAG in arguments
    try:
        if CHECK_FLAG in arguments:
            check_portable_red(PROJECT_ROOT)
        else:
            run_redbot(PROJECT_ROOT)
    except RedbotAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        if console_mode:
            _pause_after_error()
        return DUPLICATE_EXIT_CODE
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
