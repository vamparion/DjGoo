from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools import apply_update
from tools.apply_update import UpdateApplyError, apply_staged_update, safe_relative_path


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

    def fail_second(source: Path, destination: Path, timeout: float = 30.0) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise UpdateApplyError("simulated replacement failure")
        original(source, destination, timeout)

    monkeypatch.setattr(apply_update, "_atomic_copy", fail_second)

    with pytest.raises(UpdateApplyError, match="simulated replacement failure"):
        apply_staged_update(root, staging, manifest, backup)

    assert (root / "tools" / "one.py").read_text(encoding="utf-8") == "old-one"
    assert (root / "tools" / "two.py").read_text(encoding="utf-8") == "old-two"
