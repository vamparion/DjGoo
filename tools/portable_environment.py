from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from tools.app_layout import active_app_root, layered_environment


_PYINSTALLER_LEGACY_KEYS = {"_MEIPASS2"}


def clean_subprocess_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment safe for a new standalone DjGoo process.

    Alpha.24 and older one-file launchers exported private PyInstaller variables.
    Alpha.25 uses thin launchers, but cleaning these values remains necessary for
    users migrating in place from an older package.
    """

    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.startswith("_PYI_") or key in _PYINSTALLER_LEGACY_KEYS:
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def portable_local_appdata(project_root: Path) -> Path:
    return (project_root.resolve() / ".localappdata").resolve()


def red_config_dir(project_root: Path) -> Path:
    return portable_local_appdata(project_root) / "Red-DiscordBot" / "Red-DiscordBot"


def portable_environment(
    project_root: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a relocatable environment for layered or legacy DjGoo packages."""

    root = project_root.resolve()
    local_appdata = portable_local_appdata(root)
    config_dir = red_config_dir(root)
    local_appdata.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    clean = clean_subprocess_environment(base)
    env = layered_environment(root, clean)
    env["LOCALAPPDATA"] = str(local_appdata)
    env["REDBOT_CONFIG_DIR"] = str(config_dir)
    return env


def apply_portable_environment(project_root: Path) -> dict[str, str]:
    env = portable_environment(project_root)
    os.environ.clear()
    os.environ.update(env)
    return env


def bind_red_data_manager(project_root: Path, data_manager: Any | None = None) -> Path:
    """Force Red to use DjGoo's package-local configuration and data."""

    root = project_root.resolve()
    apply_portable_environment(root)
    config_dir = red_config_dir(root)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    if data_manager is None:
        from redbot.core import data_manager as red_data_manager

        data_manager = red_data_manager

    data_manager.config_dir = config_dir
    data_manager.config_file = config_file
    return config_file


def application_source_root(project_root: Path) -> Path:
    """Return the immutable active application layer for a package."""

    return active_app_root(project_root.resolve())
