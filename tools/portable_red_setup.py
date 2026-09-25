from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.app_layout import bundled_cogs_root
from tools.portable_environment import bind_red_data_manager, red_config_dir as portable_red_config_dir


DISCORD_APPS_URL = "https://discord.com/developers/applications"
INSTANCE_NAME = "discordbot"
COG_PATH_APPEND_DEFAULT = "cogs"
CORE_PATH_APPEND_DEFAULT = "core"


def red_config_dir(project_root: Path) -> Path:
    configured = os.environ.get("REDBOT_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return portable_red_config_dir(project_root)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = config_path.with_suffix(f".invalid-{int(time.time())}.json")
        shutil.copy2(config_path, backup)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _path_append(value: object, default: str) -> str:
    """Return a Red-compatible path suffix, migrating invalid old values."""

    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return default


def ensure_instance(project_root: Path) -> Path:
    """Create or repair DjGoo's portable Red instance configuration."""

    project_root = project_root.resolve()
    config_dir = red_config_dir(project_root)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    data_path = (project_root / "data" / INSTANCE_NAME).resolve()
    local_cogs = bundled_cogs_root(project_root).resolve()
    data_path.mkdir(parents=True, exist_ok=True)
    local_cogs.mkdir(parents=True, exist_ok=True)

    payload = _load_config(config_path)
    existing = payload.get(INSTANCE_NAME)
    instance = dict(existing) if isinstance(existing, dict) else {}
    instance["DATA_PATH"] = str(data_path)

    # Red's bootstrap schema requires these to be strings relative to DATA_PATH.
    # Early portable builds wrote lists here, so every setup/startup repairs them.
    instance["COG_PATH_APPEND"] = _path_append(
        instance.get("COG_PATH_APPEND"), COG_PATH_APPEND_DEFAULT
    )
    instance["CORE_PATH_APPEND"] = _path_append(
        instance.get("CORE_PATH_APPEND"), CORE_PATH_APPEND_DEFAULT
    )

    storage_type = instance.get("STORAGE_TYPE")
    if not isinstance(storage_type, str) or not storage_type.strip():
        instance["STORAGE_TYPE"] = "JSON"
    if not isinstance(instance.get("STORAGE_DETAILS"), dict):
        instance["STORAGE_DETAILS"] = {}

    payload[INSTANCE_NAME] = instance

    temp = config_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(config_path)
    return config_path


def verify_red_config_resolution(project_root: Path, prepared_config: Path) -> Path:
    """Fail setup when Red is not bound to the file DjGoo prepared."""

    actual = bind_red_data_manager(project_root).resolve()
    expected = prepared_config.resolve()
    if actual != expected:
        raise RuntimeError(
            "Red configuration path mismatch. "
            f"DjGoo prepared {expected}, but Red resolved {actual}."
        )
    return actual


def verify_red_instance_runtime(project_root: Path) -> tuple[Path, Path]:
    """Exercise Red's real data paths and core JSON driver configuration."""

    from redbot.core import data_manager
    from redbot.core.config import Config

    bind_red_data_manager(project_root, data_manager)
    data_manager.load_basic_configuration(INSTANCE_NAME)
    core_path = data_manager.core_data_path()
    cog_path = data_manager.cog_data_path()

    # This is the same initialization path that previously failed only after
    # Red's bot object was constructed.
    Config.get_core_conf(force_registration=False)
    return core_path, cog_path


def verify_update_credentials() -> bool:
    """Verify Windows DPAPI round-trips without persisting a credential."""

    if os.name != "nt":
        return False
    from tools.update_auth import protect_secret, unprotect_secret

    sentinel = f"djgoo-update-self-test-{os.getpid()}"
    protected = protect_secret(sentinel)
    if protected == sentinel or unprotect_secret(protected) != sentinel:
        raise RuntimeError("Windows could not verify encrypted DjGoo update credentials")
    return True


def ensure_project_files(project_root: Path) -> None:
    for relative in (
        "config",
        "data",
        "logs",
        "data/models",
        "data/health",
        "data/pids",
        "data/updates",
        "data/update-backups",
        "local_cogs",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)

    example = project_root / "config" / "secrets.example.json"
    secrets = project_root / "config" / "secrets.json"
    if not secrets.exists() and example.exists():
        shutil.copy2(example, secrets)


def write_marker(project_root: Path) -> None:
    marker = project_root / "data" / "portable-setup.json"
    marker.write_text(
        json.dumps(
            {
                "schema": 5,
                "instance": INSTANCE_NAME,
                "created_at": time.time(),
                "project_root": str(project_root),
                "red_config_dir": str(red_config_dir(project_root)),
                "local_cog_path": str(bundled_cogs_root(project_root).resolve()),
                "startup_cogs": ["audio", "djgoowelcome"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def prompt(message: str) -> bool:
    answer = input(f"{message} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a portable DjGoo host instance.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    bind_red_data_manager(project_root)

    print("\nDjGoo portable setup")
    print("====================")
    print(f"Folder: {project_root}\n")
    ensure_project_files(project_root)
    config_path = ensure_instance(project_root)
    verify_red_config_resolution(project_root, config_path)
    core_path, cog_path = verify_red_instance_runtime(project_root)
    dpapi_verified = verify_update_credentials()
    write_marker(project_root)

    import pip

    print(f"Created or refreshed the Red instance configuration at:\n  {config_path}\n")
    print("Verified that Red resolves this same portable configuration file.")
    print(f"Verified Red core data path:\n  {core_path}")
    print(f"Verified Red cog data path:\n  {cog_path}")
    print("Verified Red core JSON driver initialization.")
    print(f"Verified bundled pip {pip.__version__}.")
    if dpapi_verified:
        print("Verified Windows-encrypted update credential storage.")
    print()
    print(f"Registered bundled DjGoo cogs from:\n  {bundled_cogs_root(project_root).resolve()}\n")
    print("Discord requires each host owner to create their own bot application.")
    print("Never send the bot token to another user and never put it in GitHub.")
    print("Enable the Server Members, Presence, and Message Content gateway intents.")
    print(
        "Grant the bot Manage Webhooks in the text channel used for DjGoo Link. "
        "This lets DjGoo create its encrypted outbound bridge without opening router ports."
    )

    if not args.non_interactive and prompt("Open the Discord developer portal now?"):
        webbrowser.open(DISCORD_APPS_URL)

    print("\nNext steps")
    print("1. Close this window.")
    print("2. In DjGoo, choose 'Test bot console'.")
    print("3. Red will ask for the bot token and command prefix on first start.")
    print("4. DjGoo automatically loads Red Audio and the bundled djgoowelcome cog.")
    print("5. Invite the bot using the URL Red prints after it connects.")
    print("6. Grant the bot Manage Webhooks in the channel used for /djgoolink pair.")
    print("7. Close the test console before using the normal Start button.")
    if not args.non_interactive:
        input("\nPress Enter to close setup...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
