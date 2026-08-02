from __future__ import annotations

from pathlib import Path

import pytest

from tools.build_update_bundle import UpdateBundleError, collect_update_files


REQUIRED_FILES = (
    "DjGoo.exe",
    "DjGoo Mini Player.exe",
    "control_panel/state.py",
    "tools/apply_update.py",
    "tools/djgoo_stack.py",
    "tools/djgoo_stack_core.py",
    "data/installed-version.json",
    "data/lavalink-contract.json",
    "data/discordbot/cogs/Audio/Lavalink.jar",
    "data/discordbot/cogs/Audio/application.yml",
    "runtime/python/Lib/site-packages/pip/__init__.py",
)


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "host"
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    return root


def test_incremental_update_contains_mini_player(tmp_path: Path) -> None:
    root = _package(tmp_path)

    files = collect_update_files(root)
    relative = {path.relative_to(root).as_posix() for path in files}

    assert "DjGoo.exe" in relative
    assert "DjGoo Mini Player.exe" in relative
    assert "control_panel/state.py" in relative
    assert "tools/apply_update.py" in relative
    assert "tools/djgoo_stack.py" in relative
    assert "tools/djgoo_stack_core.py" in relative


def test_incremental_update_rejects_missing_mini_player(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (root / "DjGoo Mini Player.exe").unlink()

    with pytest.raises(UpdateBundleError, match="Mini Player"):
        collect_update_files(root)
