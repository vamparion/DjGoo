from __future__ import annotations

import json
from pathlib import Path

from tools.legacy_music_core import migrate_existing_music_core
from tools.portable_environment import red_config_dir


def test_existing_music_core_is_recognized_without_reentering_token(tmp_path: Path) -> None:
    data_path = tmp_path / "data" / "discordbot"
    core = data_path / "core"
    core.mkdir(parents=True)
    existing_settings = {"token_sentinel": "preserve-me"}
    (core / "settings.json").write_text(json.dumps(existing_settings), encoding="utf-8")

    config_path = red_config_dir(tmp_path) / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "discordbot": {
                    "DATA_PATH": str(data_path),
                    "COG_PATH_APPEND": "cogs",
                    "CORE_PATH_APPEND": "core",
                    "STORAGE_TYPE": "JSON",
                    "STORAGE_DETAILS": {},
                }
            }
        ),
        encoding="utf-8",
    )

    assert migrate_existing_music_core(tmp_path) is True
    assert (tmp_path / "data" / "portable-setup.json").exists()
    assert json.loads((core / "settings.json").read_text(encoding="utf-8")) == existing_settings
    assert migrate_existing_music_core(tmp_path) is False


def test_empty_instance_is_not_mistaken_for_configured_music_core(tmp_path: Path) -> None:
    config_path = red_config_dir(tmp_path) / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"discordbot": {"DATA_PATH": str(tmp_path / "data" / "discordbot")}}),
        encoding="utf-8",
    )
    assert migrate_existing_music_core(tmp_path) is False
