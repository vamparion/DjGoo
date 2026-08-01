from __future__ import annotations

from pathlib import Path

from tools.portable_environment import clean_subprocess_environment, portable_environment


def test_clean_subprocess_environment_removes_pyinstaller_private_state() -> None:
    env = clean_subprocess_environment(
        {
            "PATH": "test-path",
            "_PYI_APPLICATION_HOME_DIR": r"C:\Users\test\AppData\Local\Temp\_MEI123",
            "_PYI_ARCHIVE_FILE": r"C:\DjGoo\DjGoo.exe",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_MEIPASS2": r"C:\Users\test\AppData\Local\Temp\_MEI123",
        }
    )

    assert env["PATH"] == "test-path"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not any(key.startswith("_PYI_") for key in env)
    assert "_MEIPASS2" not in env


def test_portable_environment_carries_reset_into_update_worker(tmp_path: Path) -> None:
    env = portable_environment(
        tmp_path,
        {
            "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI456",
            "LOCALAPPDATA": r"C:\Users\test\AppData\Local",
        },
    )

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert Path(env["DJGOO_HOME"]) == tmp_path.resolve()
