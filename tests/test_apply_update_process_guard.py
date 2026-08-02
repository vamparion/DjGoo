from __future__ import annotations

from pathlib import Path

import tools.apply_update as apply_update


def test_bootloader_parent_requires_same_djgoo_executable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = (tmp_path / "DjGoo.exe").resolve()
    monkeypatch.setattr(apply_update.os, "name", "nt")
    monkeypatch.setattr(
        apply_update,
        "_windows_parent_pid",
        lambda pid: 222,
    )
    monkeypatch.setattr(
        apply_update,
        "_windows_process_image",
        lambda pid: str(expected),
    )
    monkeypatch.setattr(apply_update.os, "getpid", lambda: 999)

    assert apply_update.pyinstaller_bootloader_pid(tmp_path, 111) == 222

    monkeypatch.setattr(
        apply_update,
        "_windows_process_image",
        lambda pid: str(tmp_path / "Other.exe"),
    )
    assert apply_update.pyinstaller_bootloader_pid(tmp_path, 111) == 0


def test_wait_for_launcher_release_waits_for_both_processes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waits: list[tuple[int, float]] = []
    logs: list[str] = []
    monkeypatch.setattr(
        apply_update,
        "pyinstaller_bootloader_pid",
        lambda root, pid, launcher_name="DjGoo.exe": 222,
    )

    def wait(pid: int, timeout: float = apply_update.PARENT_EXIT_TIMEOUT_SECONDS) -> None:
        waits.append((pid, timeout))

    monkeypatch.setattr(apply_update, "wait_for_process_exit", wait)
    apply_update.wait_for_launcher_release(tmp_path, 111, logs.append)

    assert waits == [
        (111, apply_update.PARENT_EXIT_TIMEOUT_SECONDS),
        (222, apply_update.BOOTLOADER_EXIT_TIMEOUT_SECONDS),
    ]
    assert any("exited cleanly" in item for item in logs)


def test_wait_for_launcher_release_stops_stale_bootloader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waits: list[tuple[int, float]] = []
    terminated: list[tuple[int, Path]] = []
    bootloader_attempts = 0
    monkeypatch.setattr(
        apply_update,
        "pyinstaller_bootloader_pid",
        lambda root, pid, launcher_name="DjGoo.exe": 222,
    )

    def wait(pid: int, timeout: float = apply_update.PARENT_EXIT_TIMEOUT_SECONDS) -> None:
        nonlocal bootloader_attempts
        waits.append((pid, timeout))
        if pid == 222:
            bootloader_attempts += 1
            if bootloader_attempts == 1:
                raise apply_update.UpdateApplyError("still running")

    monkeypatch.setattr(apply_update, "wait_for_process_exit", wait)
    monkeypatch.setattr(
        apply_update,
        "_terminate_verified_windows_process",
        lambda pid, expected: terminated.append((pid, expected)),
    )

    logs: list[str] = []
    apply_update.wait_for_launcher_release(tmp_path, 111, logs.append)

    assert terminated == [(222, tmp_path.resolve() / "DjGoo.exe")]
    assert waits[-1] == (222, 5.0)
    assert any("Stopped stale" in item for item in logs)
