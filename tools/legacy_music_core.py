from __future__ import annotations

import json
from pathlib import Path

from tools.portable_environment import red_config_dir
from tools.portable_red_setup import INSTANCE_NAME, ensure_instance, write_marker


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_legacy_core_state(data_path: Path) -> bool:
    if not data_path.exists():
        return False
    ignored = {
        "lavalink.jar",
        "application.yml",
    }
    for path in data_path.rglob("*"):
        if not path.is_file() or path.name.lower() in ignored:
            continue
        if path.suffix.lower() in {".json", ".sqlite", ".db"}:
            return True
    return False


def migrate_existing_music_core(project_root: Path) -> bool:
    """Recognize an existing portable Music Core after a UI-only update.

    Older DjGoo releases could have a fully configured Red instance without the
    newer ``portable-setup.json`` marker. The updater preserves that instance;
    this function repairs only its path registration and creates the marker.
    It never reads, replaces, or asks for the existing Discord token.
    """

    root = project_root.resolve()
    marker = root / "data" / "portable-setup.json"
    if marker.exists():
        return False

    config_path = red_config_dir(root) / "config.json"
    payload = _load_json(config_path)
    instance = payload.get(INSTANCE_NAME)
    if not isinstance(instance, dict):
        return False

    configured_path = str(instance.get("DATA_PATH") or "").strip()
    data_path = Path(configured_path).expanduser() if configured_path else root / "data" / INSTANCE_NAME
    if not data_path.is_absolute():
        data_path = (root / data_path).resolve()
    if not _has_legacy_core_state(data_path):
        return False

    ensure_instance(root)
    write_marker(root)
    return True
