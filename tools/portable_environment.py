from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


_PYINSTALLER_LEGACY_KEYS = {"_MEIPASS2"}


def clean_subprocess_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment safe for a new standalone DjGoo process.

    A PyInstaller one-file launcher exports private ``_PYI_*`` variables that
    tell its child process to reuse the launcher's temporary ``_MEI...``
    extraction directory. Those variables must not cross into DjGoo's update
    worker or the replacement launcher: the old directory is removed when the
    original launcher exits, which otherwise makes the replacement fail to find
    ``python311.dll``.

    ``PYINSTALLER_RESET_ENVIRONMENT`` is also set for the next standalone
    executable as a defense in depth supported by current PyInstaller releases.
    Normal Python, Java, and Redbot child processes simply ignore it.
    """

    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.startswith("_PYI_") or key in _PYINSTALLER_LEGACY_KEYS:
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def portable_local_appdata(project_root: Path) -> Path:
    """Return the LocalAppData root owned by the portable package."""

    return (project_root.resolve() / ".localappdata").resolve()


def red_config_dir(project_root: Path) -> Path:
    """Return the Red configuration directory owned by the portable package."""

    return portable_local_appdata(project_root) / "Red-DiscordBot" / "Red-DiscordBot"


def portable_environment(
    project_root: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an environment that keeps DjGoo state beside the package.

    ``LOCALAPPDATA`` remains useful for dependencies that honor environment
    overrides. Red-DiscordBot's Windows path lookup can use the Windows Known
    Folder API instead, so production startup also calls
    :func:`bind_red_data_manager` before Red loads its instance configuration.
    """

    root = project_root.resolve()
    local_appdata = portable_local_appdata(root)
    config_dir = red_config_dir(root)
    local_appdata.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    env = clean_subprocess_environment(base)
    env["DJGOO_HOME"] = str(root)
    env["LOCALAPPDATA"] = str(local_appdata)
    env["REDBOT_CONFIG_DIR"] = str(config_dir)
    return env


def apply_portable_environment(project_root: Path) -> dict[str, str]:
    """Apply DjGoo's portable environment to the current process."""

    env = portable_environment(project_root)
    os.environ.clear()
    os.environ.update(env)
    return env


def bind_red_data_manager(project_root: Path, data_manager: Any | None = None) -> Path:
    """Force Red to use DjGoo's package-local ``config.json``.

    Red calculates its Windows configuration path while importing
    ``redbot.core.data_manager``. Changing ``LOCALAPPDATA`` alone is therefore
    not reliable. This function updates the module attributes Red reads during
    setup and startup, and returns the bound ``config.json`` path.

    ``data_manager`` is injectable so the path binding can be unit-tested
    without installing Red in the development test environment.
    """

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
