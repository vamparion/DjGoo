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

from tools.portable_environment import bind_red_data_manager, red_config_dir
from tools.portable_red_setup import ensure_instance, verify_red_instance_runtime
from voice.health import write_heartbeat


INSTANCE_NAME = "discordbot"
STARTUP_COGS = ("audio", "djgoowelcome")
CONSOLE_FLAG = "--djgoo-console"
CHECK_FLAG = "--djgoo-check"
DUPLICATE_EXIT_CODE = 75
SETUP_REQUIRED_EXIT_CODE = 78
LAVALINK_BIND_HOST = "::1"
# Red-Lavalink interpolates the configured host directly into ws://{host}:{port}.
# IPv6 literals therefore require brackets in the client setting.
LAVALINK_HOST = "[::1]"
LAVALINK_PORT = 2333
LAVALINK_PASSWORD = "youshallnotpass"


class RedbotAlreadyRunning(RuntimeError):
    pass


class MusicCoreSetupRequired(RuntimeError):
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


def redbot_settings_path(project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "data" / INSTANCE_NAME / "core" / "settings.json"


def redbot_latest_log_path(project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "data" / INSTANCE_NAME / "core" / "logs" / "latest.log"


def music_core_is_configured(project_root: Path = PROJECT_ROOT) -> bool:
    """Return True once Red has saved first-run bot settings.

    Red starts an interactive token prompt when the settings file is absent or
    still the initial empty JSON object. That is fine for the visible test
    console, but fatal for DjGoo's hidden supervised startup.
    """

    settings = redbot_settings_path(project_root)
    try:
        payload = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload)


def setup_required_message(project_root: Path = PROJECT_ROOT) -> str:
    return (
        "DjGoo Music Core setup is required before background startup can run.\n"
        "Open DjGoo, choose Music Core setup, then use Test bot console once "
        "to enter the Discord bot token and command prefix.\n"
        f"Red settings file: {redbot_settings_path(project_root)}"
    )


def duplicate_instance_message(project_root: Path = PROJECT_ROOT) -> str:
    return (
        "Another DjGoo Redbot process is already using this package.\n"
        "Stop DjGoo before opening the bot console. Starting a second copy would "
        "conflict with Redbot's latest.log file.\n"
        f"Current Redbot log: {redbot_latest_log_path(project_root)}"
    )


def redbot_log_contains(project_root: Path, text: str) -> bool:
    try:
        tail = redbot_latest_log_path(project_root).read_text(
            encoding="utf-8",
            errors="replace",
        )[-8000:]
    except OSError:
        return False
    return text.lower() in tail.lower()


def write_fatal_heartbeat(reason: str, message: str) -> None:
    try:
        write_heartbeat(
            "redbot",
            project_root=PROJECT_ROOT,
            fields={
                "ready": False,
                "fatal": True,
                "event": "redbot.fatal",
                "reason": reason,
                "message": message,
            },
        )
    except OSError:
        pass


def _ipv6_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
    if family not in (socket.AF_INET, socket.AF_INET6):
        raise ValueError("Only AF_INET and AF_INET6 socket pairs are supported")
    listener = socket.socket(socket.AF_INET6, type, proto)
    listener.bind((LAVALINK_BIND_HOST, 0))
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


async def configure_external_lavalink(cog: Any) -> None:
    """Restore the exact external-node contract used by working DjGoo builds."""

    await cog.config.use_external_lavalink.set(True)
    await cog.config.host.set(LAVALINK_HOST)
    await cog.config.rest_port.set(LAVALINK_PORT)
    await cog.config.ws_port.set(LAVALINK_PORT)
    await cog.config.password.set(LAVALINK_PASSWORD)
    await cog.config.secured_ws.set(False)

    # Keep Red's managed-node YAML aligned for diagnostics and future migrations.
    # The server bind address is a raw IPv6 literal; only the WebSocket client
    # host requires square brackets.
    await cog.config.yaml.server.address.set(LAVALINK_BIND_HOST)
    await cog.config.yaml.server.port.set(LAVALINK_PORT)
    await cog.config.yaml.lavalink.server.password.set(LAVALINK_PASSWORD)


async def monitor_lavalink_client(project_root: Path = PROJECT_ROOT) -> None:
    """Publish health from Red-Lavalink's real WebSocket node state."""

    import lavalink

    while True:
        nodes: list[Any] = []
        ready_nodes: list[Any] = []
        error = ""
        try:
            nodes = list(lavalink.get_all_nodes())
            ready_nodes = [node for node in nodes if bool(getattr(node, "ready", False))]
        except Exception as exc:  # Health reporting must never crash Red.
            error = f"{type(exc).__name__}: {exc}"
        try:
            write_heartbeat(
                "lavalink-client",
                project_root=project_root,
                fields={
                    "ready": bool(ready_nodes),
                    "node_count": len(nodes),
                    "ready_node_count": len(ready_nodes),
                    "host": LAVALINK_HOST,
                    "port": LAVALINK_PORT,
                    "error": error,
                },
            )
        except OSError:
            pass
        await asyncio.sleep(2)


def install_audio_runtime_patch(
    audio_package: Any,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Apply the external-node settings before Red Audio initializes."""

    audio_class = audio_package.Audio
    if bool(getattr(audio_class, "_djgoo_external_lavalink_patch", False)):
        return

    original_initialize = audio_class.initialize

    async def djgoo_initialize(self: Any) -> None:
        await configure_external_lavalink(self)
        await original_initialize(self)
        task = getattr(self, "_djgoo_lavalink_health_task", None)
        if task is None or task.done():
            self._djgoo_lavalink_health_task = asyncio.create_task(
                monitor_lavalink_client(project_root)
            )

    audio_class.initialize = djgoo_initialize
    audio_class._djgoo_external_lavalink_patch = True
    audio_class._djgoo_original_initialize = original_initialize


def apply_runtime_patches(project_root: Path = PROJECT_ROOT) -> None:
    socket.socketpair = _ipv6_socketpair
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    apply_bundled_java_environment(project_root)

    import redbot.cogs.audio as audio_package
    from redbot.cogs.audio.managed_node import ll_server_config

    ll_server_config.DEFAULT_LAVALINK_YAML["yaml__server__address"] = LAVALINK_BIND_HOST
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


def run_redbot(project_root: Path = PROJECT_ROOT, *, allow_interactive_setup: bool = False) -> None:
    instance = SingleInstance(redbot_lock_path(project_root))
    if not instance.acquire():
        raise RedbotAlreadyRunning(duplicate_instance_message(project_root))
    try:
        ensure_instance(project_root)
        bind_red_data_manager(project_root)
        if not allow_interactive_setup and not music_core_is_configured(project_root):
            raise MusicCoreSetupRequired(setup_required_message(project_root))
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
            run_redbot(PROJECT_ROOT, allow_interactive_setup=console_mode)
    except RedbotAlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        if console_mode:
            _pause_after_error()
        return DUPLICATE_EXIT_CODE
    except MusicCoreSetupRequired as exc:
        print(str(exc), file=sys.stderr)
        try:
            write_heartbeat(
                "redbot",
                project_root=PROJECT_ROOT,
                fields={
                    "ready": False,
                    "setup_required": True,
                    "event": "redbot.setup_required",
                    "reason": "music-core-setup-required",
                    "message": setup_required_message(PROJECT_ROOT),
                },
            )
        except OSError:
            pass
        if console_mode:
            _pause_after_error()
        return SETUP_REQUIRED_EXIT_CODE
    except SystemExit as exc:
        code = _exit_code(exc.code)
        if code != 0 and redbot_log_contains(
            PROJECT_ROOT,
            "token doesn't seem to be valid",
        ):
            write_fatal_heartbeat(
                "invalid-discord-token",
                (
                    "Discord rejected DjGoo's bot token. "
                    "Open Music Core setup and paste a fresh Discord bot token."
                ),
            )
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
