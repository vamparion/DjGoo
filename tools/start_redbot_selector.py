from __future__ import annotations

import asyncio
import json
import runpy
import socket
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.portable_environment import bind_red_data_manager, red_config_dir
from tools.portable_red_setup import ensure_instance, verify_red_instance_runtime


INSTANCE_NAME = "discordbot"
STARTUP_COGS = ("audio", "djgoowelcome")
CONSOLE_FLAG = "--djgoo-console"
CHECK_FLAG = "--djgoo-check"


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
    # Always migrate early portable configurations before Red reads them.
    ensure_instance(project_root)
    bind_red_data_manager(project_root)
    apply_runtime_patches()
    sys.argv = redbot_argv(project_root)
    runpy.run_module("redbot", run_name="__main__")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    console_mode = CONSOLE_FLAG in arguments
    try:
        if CHECK_FLAG in arguments:
            check_portable_red(PROJECT_ROOT)
        else:
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
