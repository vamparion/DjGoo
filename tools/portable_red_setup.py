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

from tools.portable_environment import (
    apply_portable_environment,
    red_config_dir as portable_red_config_dir,
)


DISCORD_APPS_URL = "https://discord.com/developers/applications"
INSTANCE_NAME = "discordbot"


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


def _deduplicated_paths(values: object, required: Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    candidates = values if isinstance(values, list) else []
    for value in [*candidates, str(required.resolve())]:
        text = str(value).strip()
        if not text:
            continue
        normalized = os.path.normcase(os.path.abspath(os.path.expanduser(text)))
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(str(Path(text).expanduser().resolve()))
    return paths


def ensure_instance(project_root: Path) -> Path:
    project_root = project_root.resolve()
    config_dir = red_config_dir(project_root)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    data_path = (project_root / "data" / INSTANCE_NAME).resolve()
    local_cogs = (project_root / "local_cogs").resolve()
    data_path.mkdir(parents=True, exist_ok=True)
    local_cogs.mkdir(parents=True, exist_ok=True)

    payload = _load_config(config_path)
    existing = payload.get(INSTANCE_NAME)
    instance = dict(existing) if isinstance(existing, dict) else {}
    instance["DATA_PATH"] = str(data_path)
    instance["COG_PATH_APPEND"] = _deduplicated_paths(instance.get("COG_PATH_APPEND"), local_cogs)
    instance.setdefault("CORE_PATH_APPEND", [])
    instance.setdefault("STORAGE_TYPE", "JSON")
    instance.setdefault("STORAGE_DETAILS", {})
    payload[INSTANCE_NAME] = instance

    temp = config_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(config_path)
    return config_path


def verify_red_config_resolution(project_root: Path, prepared_config: Path) -> Path:
    """Fail setup when Red resolves a different config file than DjGoo prepared."""

    from redbot.core import data_manager

    actual = data_manager.config_file.resolve()
    expected = prepared_config.resolve()
    if actual != expected:
        raise RuntimeError(
            "Red configuration path mismatch. "
            f"DjGoo prepared {expected}, but Red resolved {actual}."
        )
    return actual


def ensure_project_files(project_root: Path) -> None:
    for relative in (
        "config",
        "data",
        "logs",
        "data/models",
        "data/health",
        "data/pids",
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
                "schema": 3,
                "instance": INSTANCE_NAME,
                "created_at": time.time(),
                "project_root": str(project_root),
                "red_config_dir": str(red_config_dir(project_root)),
                "local_cog_path": str((project_root / "local_cogs").resolve()),
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
    apply_portable_environment(project_root)

    print("\nDjGoo portable setup")
    print("====================")
    print(f"Folder: {project_root}\n")
    ensure_project_files(project_root)
    config_path = ensure_instance(project_root)
    verify_red_config_resolution(project_root, config_path)
    write_marker(project_root)

    print(f"Created or refreshed the Red instance configuration at:\n  {config_path}\n")
    print("Verified that Red resolves this same portable configuration file.\n")
    print(f"Registered bundled DjGoo cogs from:\n  {(project_root / 'local_cogs').resolve()}\n")
    print("Discord requires each host owner to create their own bot application.")
    print("Never send the bot token to another user and never put it in GitHub.")
    print("Enable the Server Members, Presence, and Message Content gateway intents.")

    if not args.non_interactive and prompt("Open the Discord developer portal now?"):
        webbrowser.open(DISCORD_APPS_URL)

    print("\nNext steps")
    print("1. Close this window.")
    print("2. In DjGoo, choose 'Test bot console'.")
    print("3. Red will ask for the bot token and command prefix on first start.")
    print("4. DjGoo automatically loads Red Audio and the bundled djgoowelcome cog.")
    print("5. Invite the bot using the URL Red prints after it connects.")
    print("6. Close the test console before using the normal Start button.")
    if not args.non_interactive:
        input("\nPress Enter to close setup...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
