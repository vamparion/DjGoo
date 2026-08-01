from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import webbrowser
from pathlib import Path


DISCORD_APPS_URL = "https://discord.com/developers/applications"
INSTANCE_NAME = "discordbot"


def red_config_dir(project_root: Path) -> Path:
    configured = os.environ.get("REDBOT_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured)
    return project_root / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"


def ensure_instance(project_root: Path) -> Path:
    config_dir = red_config_dir(project_root)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    data_path = project_root / "data" / INSTANCE_NAME
    data_path.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object]
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            backup = config_path.with_suffix(f".invalid-{int(time.time())}.json")
            shutil.copy2(config_path, backup)
            payload = {}
    else:
        payload = {}

    payload[INSTANCE_NAME] = {
        "DATA_PATH": str(data_path),
        "COG_PATH_APPEND": [],
        "CORE_PATH_APPEND": [],
        "STORAGE_TYPE": "JSON",
        "STORAGE_DETAILS": {},
    }
    temp = config_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(config_path)
    return config_path


def ensure_project_files(project_root: Path) -> None:
    for relative in ("config", "data", "logs", "data/models", "data/health", "data/pids"):
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
                "schema": 1,
                "instance": INSTANCE_NAME,
                "created_at": time.time(),
                "project_root": str(project_root),
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
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()

    print("\nDjGoo portable setup")
    print("====================")
    print(f"Folder: {project_root}\n")
    ensure_project_files(project_root)
    config_path = ensure_instance(project_root)
    write_marker(project_root)

    print(f"Created or refreshed the Red instance configuration at:\n  {config_path}\n")
    print("Discord requires each host owner to create their own bot application.")
    print("Never send the bot token to another user and never put it in GitHub.")
    print("Enable the Server Members, Presence, and Message Content gateway intents.")

    if not args.non_interactive and prompt("Open the Discord developer portal now?"):
        webbrowser.open(DISCORD_APPS_URL)

    print("\nNext steps")
    print("1. Close this window.")
    print("2. In DjGoo, choose 'Test bot console'.")
    print("3. Red will ask for the bot token, command prefix, and owner information on first start.")
    print("4. Invite the bot using the URL Red prints after it connects.")
    print("5. Close the console and use the normal Start button.")
    if not args.non_interactive:
        input("\nPress Enter to close setup...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
