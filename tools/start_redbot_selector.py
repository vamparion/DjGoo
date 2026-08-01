from __future__ import annotations

import asyncio
import json
import os
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
LAVALINK_HOST = "::1"
LAVALINK_PORT = 2333
LAVALINK_PASSWORD = "youshallnotpass"


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
    listener.bind((LAVALINK_HOST, 0))
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


def bundled_java_executable(project_root: Path = PROJECT_ROOT) -> Path:
    return (project_root.resolve() / "runtime" / "java" / "bin" / "java.exe").resolve()


def apply_bundled_java_environment(project_root: Path = PROJECT_ROOT) -> Path:
    java = bundled_java_executable(project_root)
    if not java.exists():
        return java
    java_home = java.parents[1]
    os.environ["JAVA_HOME"] = str(java_home)
    current_path = os.environ.get("PATH", "")
    java_bin = str(java.parent)
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    if not path_parts or os.path.normcase(path_parts[0]) != os.path.normcase(java_bin):
        os.environ["PATH"] = os.pathsep.join([java_bin, *path_parts])
    return java


async def configure_managed_lavalink(
    cog: Any,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Restore DjGoo's last known-good Red-managed Lavalink settings.

    The portable stack previously worked by binding both Lavalink and Red's
    client to IPv6 loopback and by using a known Java runtime. Later alpha builds
    only disabled external-node mode, leaving stale/default ``localhost`` and
    machine-wide Java settings behind. Apply the full managed-node contract
    before Audio initializes.
    """

    java = apply_bundled_java_environment(project_root)
    await cog.config.use_external_lavalink.set(False)
    if java.exists():
        await cog.config.java_exc_path.set(str(java))

    await cog.config.yaml.server.address.set(LAVALINK_HOST)
    await cog.config.yaml.server.port.set(LAVALINK_PORT)
    await cog.config.yaml.lavalink.server.password.set(LAVALINK_PASSWORD)

    # Keep the external-node fields aligned as well so switching modes or
    # reading diagnostics never exposes contradictory values.
    await cog.config.host.set(LAVALINK_HOST)
    await cog.config.rest_port.set(LAVALINK_PORT)
    await cog.config.ws_port.set(LAVALINK_PORT)
    await cog.config.password.set(LAVALINK_PASSWORD)
    await cog.config.secured_ws.set(False)


def install_audio_runtime_patch(
    audio_package: Any,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Apply portable managed-node settings before Red Audio initializes."""

    audio_class = audio_package.Audio
    if bool(getattr(audio_class, "_djgoo_managed_lavalink_patch", False)):
        return

    original_initialize = audio_class.initialize

    async def djgoo_initialize(self: Any) -> None:
        await configure_managed_lavalink(self, project_root)
        await original_initialize(self)

    audio_class.initialize = djgoo_initialize
    audio_class._djgoo_managed_lavalink_patch = True
    audio_class._djgoo_original_initialize = original_initialize


def apply_runtime_patches(project_root: Path = PROJECT_ROOT) -> None:
    socket.socketpair = _ipv6_socketpair
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    apply_bundled_java_environment(project_root)

    import redbot.cogs.audio as audio_package
    from redbot.cogs.audio.managed_node import ll_server_config

    # New instances register defaults from this dictionary. Existing instances
    # are migrated by configure_managed_lavalink() above.
    ll_server_config.DEFAULT_LAVALINK_YAML["yaml__server__address"] = LAVALINK_HOST
    ll_server_config.DEFAULT_LAVALINK_YAML["yaml__server__port"] = LAVALINK_PORT
    ll_server_config.DEFAULT_LAVALINK_YAML[
        "yaml__lavalink__server__password"
    ] = LAVALINK_PASSWORD
    install_audio_runtime_patch(audio_package, project_root)


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
        apply_runtime_patches(project_root)
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
