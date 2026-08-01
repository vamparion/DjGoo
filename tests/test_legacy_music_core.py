from __future__ import annotations

import json
from pathlib import Path

from tools.legacy_music_core import migrate_existing_music_core
from tools.portable_environment import red_config_dir


def _write_instance_config(installation: Path, data_path: Path) -> None:
    config_path = red_config_dir(installation) / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
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


def test_existing_music_core_is_recognized_without_reentering_token(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "data" / "discordbot"
    core = data_path / "core"
    core.mkdir(parents=True)
    existing_settings = {"token_sentinel": "preserve-me"}
    (core / "settings.json").write_text(
        json.dumps(existing_settings),
        encoding="utf-8",
    )
    _write_instance_config(tmp_path, data_path)

    assert migrate_existing_music_core(tmp_path) is True
    assert (tmp_path / "data" / "portable-setup.json").exists()
    assert json.loads(
        (core / "settings.json").read_text(encoding="utf-8")
    ) == existing_settings
    assert migrate_existing_music_core(tmp_path) is False


def test_moved_install_copies_user_state_but_keeps_new_audio_engine(
    tmp_path: Path,
) -> None:
    old_install = tmp_path / "DjGoo-old"
    new_install = tmp_path / "DjGoo-new"
    old_data = old_install / "data" / "discordbot"
    old_core = old_data / "core"
    old_core.mkdir(parents=True)
    (old_core / "settings.json").write_text(
        json.dumps({"token_sentinel": "from-old-install"}),
        encoding="utf-8",
    )
    old_audio = old_data / "cogs" / "Audio"
    old_audio.mkdir(parents=True)
    (old_audio / "Lavalink.jar").write_bytes(b"old-managed-jar")
    (old_audio / "application.yml").write_text("old-managed-yaml", encoding="utf-8")
    _write_instance_config(old_install, old_data)

    new_audio = new_install / "data" / "discordbot" / "cogs" / "Audio"
    new_audio.mkdir(parents=True)
    (new_audio / "Lavalink.jar").write_bytes(b"new-managed-jar")
    (new_audio / "application.yml").write_text("new-managed-yaml", encoding="utf-8")

    assert migrate_existing_music_core(new_install) is True

    migrated_core = new_install / "data" / "discordbot" / "core" / "settings.json"
    assert json.loads(migrated_core.read_text(encoding="utf-8")) == {
        "token_sentinel": "from-old-install"
    }
    assert (new_audio / "Lavalink.jar").read_bytes() == b"new-managed-jar"
    assert (new_audio / "application.yml").read_text(encoding="utf-8") == "new-managed-yaml"

    current_config = json.loads(
        (red_config_dir(new_install) / "config.json").read_text(encoding="utf-8")
    )
    assert Path(current_config["discordbot"]["DATA_PATH"]).resolve() == (
        new_install / "data" / "discordbot"
    ).resolve()


def test_empty_instance_is_not_mistaken_for_configured_music_core(
    tmp_path: Path,
) -> None:
    _write_instance_config(tmp_path, tmp_path / "data" / "discordbot")
    assert migrate_existing_music_core(tmp_path) is False
