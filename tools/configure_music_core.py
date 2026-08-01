from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.portable_environment import bind_red_data_manager
from tools.portable_red_setup import ensure_instance


INSTANCE_NAME = "discordbot"
TOKEN_ENV = "DJGOO_SETUP_DISCORD_TOKEN"
PREFIX_ENV = "DJGOO_SETUP_COMMAND_PREFIX"


def validate_token(token: str) -> str:
    normalized = token.strip()
    if len(normalized) < 50 or any(character.isspace() for character in normalized):
        raise ValueError("The Discord bot token does not look valid")
    return normalized


def validate_prefix(prefix: str) -> str:
    normalized = prefix.strip()
    if not normalized:
        raise ValueError("The command prefix cannot be empty")
    if normalized.startswith("/"):
        raise ValueError("The command prefix cannot start with /")
    if len(normalized) > 10:
        raise ValueError("The command prefix must be 10 characters or fewer")
    return normalized


def configure(project_root: Path = PROJECT_ROOT) -> None:
    token = validate_token(os.environ.pop(TOKEN_ENV, ""))
    prefix = validate_prefix(os.environ.pop(PREFIX_ENV, "!"))
    ensure_instance(project_root)
    bind_red_data_manager(project_root)

    # The secret is supplied through the child environment, removed immediately,
    # and inserted into the in-process argument list only after Python has
    # started. It therefore never appears in the Windows process command line.
    sys.argv = [
        "djgoo-music-core",
        INSTANCE_NAME,
        "--edit",
        "--no-prompt",
        "--token",
        token,
        "--prefix",
        prefix,
    ]
    runpy.run_module("redbot", run_name="__main__")


def main() -> int:
    try:
        configure(PROJECT_ROOT)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
