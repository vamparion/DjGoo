from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def portable_local_appdata(project_root: Path) -> Path:
    """Return the Windows LocalAppData root owned by the portable package."""

    return (project_root.resolve() / ".localappdata").resolve()


def red_config_dir(project_root: Path) -> Path:
    """Return the path platformdirs/Red will use below portable LOCALAPPDATA."""

    return portable_local_appdata(project_root) / "Red-DiscordBot" / "Red-DiscordBot"


def portable_environment(
    project_root: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an environment that keeps Red and DjGoo state beside the package.

    Red-DiscordBot uses ``platformdirs.PlatformDirs`` and therefore reads
    ``LOCALAPPDATA`` on Windows. ``REDBOT_CONFIG_DIR`` is retained only as a
    compatibility hint for DjGoo's own setup helpers; Red itself does not read it.
    """

    root = project_root.resolve()
    local_appdata = portable_local_appdata(root)
    config_dir = red_config_dir(root)
    local_appdata.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ if base is None else base)
    env["DJGOO_HOME"] = str(root)
    env["LOCALAPPDATA"] = str(local_appdata)
    env["REDBOT_CONFIG_DIR"] = str(config_dir)
    return env


def apply_portable_environment(project_root: Path) -> dict[str, str]:
    """Apply the portable environment before importing Red-DiscordBot."""

    env = portable_environment(project_root)
    os.environ.update(env)
    return env
