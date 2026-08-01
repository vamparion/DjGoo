from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterator

from tools.portable_environment import red_config_dir
from tools.portable_red_setup import INSTANCE_NAME, ensure_instance, write_marker


_MANAGED_AUDIO_FILES = {
    Path("cogs/Audio/Lavalink.jar"),
    Path("cogs/Audio/application.yml"),
}
_STATE_SUFFIXES = {".json", ".sqlite", ".sqlite3", ".db"}


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _instance_from_config(
    config_path: Path,
) -> tuple[dict[str, object], dict[str, object]] | None:
    payload = _load_json(config_path)
    instance = payload.get(INSTANCE_NAME)
    if not isinstance(instance, dict):
        return None
    return payload, dict(instance)


def _resolve_data_path(
    instance: dict[str, object],
    installation_root: Path,
) -> Path:
    configured = str(instance.get("DATA_PATH") or "").strip()
    if not configured:
        return (installation_root / "data" / INSTANCE_NAME).resolve()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = installation_root / path
    return path.resolve()


def _has_legacy_core_state(data_path: Path) -> bool:
    if not data_path.exists():
        return False
    for path in data_path.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(data_path)
        except ValueError:
            continue
        if relative in _MANAGED_AUDIO_FILES:
            continue
        if path.suffix.lower() in _STATE_SUFFIXES:
            return True
    return False


def _current_registration_ready(root: Path, marker: Path) -> bool:
    if not marker.exists():
        return False
    loaded = _instance_from_config(red_config_dir(root) / "config.json")
    if loaded is None:
        return False
    _, instance = loaded
    expected = (root / "data" / INSTANCE_NAME).resolve()
    configured = _resolve_data_path(instance, root)
    return configured == expected and _has_legacy_core_state(expected)


def _candidate_config_paths(root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield current and immediate-sibling portable Red configurations."""

    current = red_config_dir(root) / "config.json"
    yielded: set[Path] = set()

    def emit(installation: Path, config: Path):
        resolved = config.resolve()
        if resolved in yielded or not config.exists():
            return None
        yielded.add(resolved)
        return installation.resolve(), config

    first = emit(root, current)
    if first is not None:
        yield first

    try:
        siblings = list(root.parent.iterdir())
    except OSError:
        siblings = []
    for sibling in siblings:
        if not sibling.is_dir() or sibling.resolve() == root:
            continue
        candidate = red_config_dir(sibling) / "config.json"
        item = emit(sibling, candidate)
        if item is not None:
            yield item


def _select_existing_instance(
    root: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, object], Path] | None:
    candidates: list[
        tuple[float, Path, Path, dict[str, object], dict[str, object], Path]
    ] = []
    for installation, config_path in _candidate_config_paths(root):
        loaded = _instance_from_config(config_path)
        if loaded is None:
            continue
        payload, instance = loaded
        data_path = _resolve_data_path(instance, installation)
        if not _has_legacy_core_state(data_path):
            continue
        try:
            modified = max(config_path.stat().st_mtime, data_path.stat().st_mtime)
        except OSError:
            modified = 0.0
        candidates.append(
            (modified, installation, config_path, payload, instance, data_path)
        )
    if not candidates:
        return None
    _, installation, config_path, payload, instance, data_path = max(
        candidates,
        key=lambda item: item[0],
    )
    return installation, config_path, payload, instance, data_path


def _copy_user_state(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative in _MANAGED_AUDIO_FILES:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def migrate_existing_music_core(project_root: Path) -> bool:
    """Recognize and preserve a configured Music Core from an older package.

    Alpha builds could contain a valid Red/Discord configuration without the
    newer ``portable-setup.json`` marker. They could also retain an absolute
    ``DATA_PATH`` or a stale marker after the package folder was moved. This
    migration detects the current installation or one immediate sibling, copies
    only user-owned Red state into the current package, preserves the newly
    bundled Audio Engine, repairs the instance path, and writes a current setup
    marker. It never interprets or replaces the Discord token itself.
    """

    root = project_root.resolve()
    marker = root / "data" / "portable-setup.json"
    if _current_registration_ready(root, marker):
        return False

    selected = _select_existing_instance(root)
    if selected is None:
        # A copied marker without usable Red state must not suppress first-run
        # setup in the launcher.
        marker.unlink(missing_ok=True)
        return False
    _, _, source_payload, source_instance, source_data = selected

    destination_data = (root / "data" / INSTANCE_NAME).resolve()
    _copy_user_state(source_data, destination_data)

    current_config = red_config_dir(root) / "config.json"
    current_payload = _load_json(current_config)
    if not current_payload:
        current_payload = dict(source_payload)
    current_payload[INSTANCE_NAME] = dict(source_instance)
    _write_json(current_config, current_payload)

    ensure_instance(root)
    write_marker(root)
    return True
