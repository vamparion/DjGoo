from __future__ import annotations

import json
from pathlib import Path

from tools.portable_red_setup import INSTANCE_NAME, ensure_instance
from tools.start_redbot_selector import STARTUP_COGS, redbot_argv


def test_setup_registers_bundled_local_cogs_and_preserves_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    existing_cog = tmp_path / "third-party-cogs"
    config_path.write_text(
        json.dumps(
            {
                INSTANCE_NAME: {
                    "DATA_PATH": "old-path",
                    "COG_PATH_APPEND": [str(existing_cog), str(existing_cog)],
                    "CORE_PATH_APPEND": ["keep-this"],
                    "STORAGE_TYPE": "JSON",
                    "STORAGE_DETAILS": {"custom": True},
                    "EXTRA_SETTING": "preserve-me",
                },
                "another-instance": {"DATA_PATH": "leave-alone"},
            }
        ),
        encoding="utf-8",
    )

    result = ensure_instance(tmp_path)
    payload = json.loads(result.read_text(encoding="utf-8"))
    instance = payload[INSTANCE_NAME]

    assert Path(instance["DATA_PATH"]) == (tmp_path / "data" / INSTANCE_NAME).resolve()
    assert instance["COG_PATH_APPEND"] == [
        str(existing_cog.resolve()),
        str((tmp_path / "local_cogs").resolve()),
    ]
    assert instance["CORE_PATH_APPEND"] == ["keep-this"]
    assert instance["STORAGE_DETAILS"] == {"custom": True}
    assert instance["EXTRA_SETTING"] == "preserve-me"
    assert payload["another-instance"] == {"DATA_PATH": "leave-alone"}


def test_setup_recovers_from_malformed_config(tmp_path: Path) -> None:
    config_dir = tmp_path / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text("not valid json", encoding="utf-8")

    ensure_instance(tmp_path)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert INSTANCE_NAME in payload
    assert list(config_dir.glob("config.invalid-*.json"))


def test_startup_forces_audio_and_djgoo_cogs_from_absolute_path(tmp_path: Path) -> None:
    argv = redbot_argv(tmp_path)
    cog_path_index = argv.index("--cog-path") + 1
    load_index = argv.index("--load-cogs") + 1

    assert Path(argv[cog_path_index]) == (tmp_path / "local_cogs").resolve()
    assert tuple(argv[load_index:]) == STARTUP_COGS == ("audio", "djgoowelcome")
