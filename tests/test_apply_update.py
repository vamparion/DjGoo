from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools import update_apply_engine as apply_update
from tools.update_apply_engine import (
    UpdateApplyError,
    apply_staged_update,
    safe_relative_path,
    wait_for_executable_release,
)


def _entry(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


@pytest.mark.parametrize(
    "value",
    ["", "../escape.txt", "/absolute.txt", "C:/windows.txt", "folder/../../escape"],
)
def test_unsafe_update_paths_are_rejected(value: str) -> None:
    with pytest.raises(UpdateApplyError):
        safe_relative_path(value)


def test_apply_update_replaces_only_listed_files_and_preserves_user_data(tmp_path: Path) -> None:
    root = tmp_path / "install"
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    (root / "tools").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (staging / "tools").mkdir(parents=True)

    (root / "tools" / "app.py").write_text("old", encoding="utf-8")
    (root / "data" / "history.json").write_text("keep-data", encoding="utf-8")
    (root / "config" / "secrets.json").write_text("keep-secret", encoding="utf-8")
    new_content = b"new"
    (staging / "tools" / "app.py").write_bytes(new_content)
    manifest = {"files": [_entry("tools/app.py", new_content)], "deletes": []}

    apply_staged_update(root, staging, manifest, backup)

    assert (root / "tools" / "app.py").read_text(encoding="utf-8") == "new"
    assert (root / "data" / "history.json").read_text(encoding="utf-8") == "keep-data"
    assert (root / "config" / "secrets.json").read_text(encoding="utf-8") == "keep-secret"
    assert (backup / "tools" / "app.py").read_text(encoding="utf-8") == "old"


def test_failed_update_rolls_back_already_replaced_files(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    for directory in (root / "tools", staging / "tools"):
        directory.mkdir(parents=True)

    (root / "tools" / "one.py").write_text("old-one", encoding="utf-8")
    (root / "tools" / "two.py").write_text("old-two", encoding="utf-8")
    one = b"new-one"
    two = b"new-two"
    (staging / "tools" / "one.py").write_bytes(one)
    (staging / "tools" / "two.py").write_bytes(two)
    manifest = {
        "files": [_entry("tools/one.py", one), _entry("tools/two.py", two)],
        "deletes": [],
    }

    original = apply_update._atomic_copy
    calls = {"count": 0}

    def fail_second(source: Path, destination: Path, timeout: float = 60.0) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise UpdateApplyError("simulated replacement failure")
        original(source, destination, timeout)

    monkeypatch.setattr(apply_update, "_atomic_copy", fail_second)

    with pytest.raises(UpdateApplyError, match="simulated replacement failure"):
        apply_staged_update(root, staging, manifest, backup)

    assert (root / "tools" / "one.py").read_text(encoding="utf-8") == "old-one"
    assert (root / "tools" / "two.py").read_text(encoding="utf-8") == "old-two"


def test_failed_first_replacement_is_not_rolled_back_as_if_modified(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "install"
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    root.mkdir()
    staging.mkdir()
    destination = root / "DjGoo.exe"
    source = staging / "DjGoo.exe"
    destination.write_bytes(b"old-launcher")
    source.write_bytes(b"new-launcher")
    manifest = {
        "files": [_entry("DjGoo.exe", b"new-launcher")],
        "deletes": [],
    }
    calls: list[tuple[Path, Path]] = []

    def fail_copy(source_path: Path, destination_path: Path, timeout: float = 60.0) -> None:
        calls.append((source_path, destination_path))
        raise UpdateApplyError("launcher is locked")

    monkeypatch.setattr(apply_update, "_atomic_copy", fail_copy)

    with pytest.raises(UpdateApplyError, match="launcher is locked"):
        apply_staged_update(root, staging, manifest, backup)

    assert calls == [(source, destination)]
    assert destination.read_bytes() == b"old-launcher"
    assert (backup / "DjGoo.exe").read_bytes() == b"old-launcher"


def test_wait_for_executable_release_terminates_only_reported_exact_path_pids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    launcher = tmp_path / "DjGoo.exe"
    launcher.write_bytes(b"launcher")
    responses = iter(({4101, 4102}, set()))
    terminated: list[set[int]] = []

    monkeypatch.setattr(apply_update.os, "name", "nt")
    monkeypatch.setattr(
        apply_update,
        "_windows_pids_for_executable",
        lambda _path: set(next(responses)),
    )
    monkeypatch.setattr(
        apply_update,
        "_terminate_windows_pids",
        lambda pids: terminated.append(set(pids)),
    )

    wait_for_executable_release(
        launcher,
        graceful_timeout=0,
        terminate_timeout=0,
    )

    assert terminated == [{4101, 4102}]
