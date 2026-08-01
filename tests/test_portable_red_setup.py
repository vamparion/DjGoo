from __future__ import annotations

import builtins
import json
from pathlib import Path
from types import SimpleNamespace

from launcher.djgoo_launcher import Layout
from tools.portable_environment import bind_red_data_manager, portable_environment, red_config_dir
from tools.portable_red_setup import INSTANCE_NAME, ensure_instance
from tools import start_redbot_selector
from tools.start_redbot_selector import CONSOLE_FLAG, STARTUP_COGS, redbot_argv


def test_portable_environment_redirects_red_to_package_local_appdata(tmp_path: Path) -> None:
    env = portable_environment(tmp_path, {"PATH": "test-path", "LOCALAPPDATA": "system-path"})

    assert env["PATH"] == "test-path"
    assert Path(env["DJGOO_HOME"]) == tmp_path.resolve()
    assert Path(env["LOCALAPPDATA"]) == (tmp_path / ".localappdata").resolve()
    assert Path(env["REDBOT_CONFIG_DIR"]) == red_config_dir(tmp_path)
    assert red_config_dir(tmp_path) == (
        tmp_path / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"
    ).resolve()


def test_bind_red_data_manager_overrides_precomputed_windows_path(tmp_path: Path) -> None:
    fake = SimpleNamespace(
        config_dir=Path("C:/Users/test/AppData/Local/Red-DiscordBot/Red-DiscordBot"),
        config_file=Path("C:/Users/test/AppData/Local/Red-DiscordBot/Red-DiscordBot/config.json"),
    )

    result = bind_red_data_manager(tmp_path, fake)

    assert result == red_config_dir(tmp_path) / "config.json"
    assert fake.config_dir == red_config_dir(tmp_path)
    assert fake.config_file == result


def test_setup_registers_bundled_local_cogs_and_preserves_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REDBOT_CONFIG_DIR", str(red_config_dir(tmp_path)))
    config_dir = red_config_dir(tmp_path)
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


def test_setup_recovers_from_malformed_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REDBOT_CONFIG_DIR", str(red_config_dir(tmp_path)))
    config_dir = red_config_dir(tmp_path)
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


def test_launcher_layout_exposes_update_and_console_helpers(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    assert layout.bot_console_script == tmp_path / "tools" / "start_redbot_selector.py"
    assert layout.update_worker == tmp_path / "tools" / "apply_update.py"
    assert layout.update_auth == tmp_path / "config" / "update-auth.json"


def test_console_mode_keeps_nonzero_red_exit_visible(monkeypatch) -> None:
    prompts: list[str] = []

    def fail(_project_root: Path) -> None:
        raise SystemExit(78)

    monkeypatch.setattr(start_redbot_selector, "run_redbot", fail)
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or "")

    assert start_redbot_selector.main([CONSOLE_FLAG]) == 78
    assert prompts == ["\nPress Enter to close this window..."]


def test_supervisor_mode_never_waits_for_console_input(monkeypatch) -> None:
    def fail(_project_root: Path) -> None:
        raise SystemExit(78)

    monkeypatch.setattr(start_redbot_selector, "run_redbot", fail)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("supervisor must not pause")),
    )

    assert start_redbot_selector.main([]) == 78
