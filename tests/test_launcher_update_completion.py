from __future__ import annotations

import shutil
from pathlib import Path

from tools import complete_launcher_update as completion
from tools import djgoo_portable_stack_entry as portable_entry


def test_deferred_launcher_completion_installs_pending_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pending = tmp_path / "tools" / "pending_launchers"
    pending.mkdir(parents=True)
    (pending / "DjGoo.exe").write_bytes(b"new-host")
    (pending / "DjGoo Mini Player.exe").write_bytes(b"new-mini")
    (tmp_path / "DjGoo.exe").write_bytes(b"old-host")
    (tmp_path / "DjGoo Mini Player.exe").write_bytes(b"old-mini")

    stopped: list[Path] = []
    restarted: list[Path] = []
    monkeypatch.setattr(
        completion,
        "stop_matching_launchers",
        lambda root, log: stopped.append(root),
    )
    monkeypatch.setattr(
        completion,
        "_atomic_replace",
        lambda source, destination, root, log: shutil.copy2(source, destination),
    )
    monkeypatch.setattr(
        completion,
        "_restart_host_if_needed",
        lambda root, log: restarted.append(root),
    )

    assert completion.complete_launcher_update(tmp_path) is True
    assert (tmp_path / "DjGoo.exe").read_bytes() == b"new-host"
    assert (tmp_path / "DjGoo Mini Player.exe").read_bytes() == b"new-mini"
    assert not pending.exists()
    assert stopped == [tmp_path.resolve()]
    assert restarted == [tmp_path.resolve()]
    assert (tmp_path / "data" / "launcher-update-complete.json").is_file()


def test_portable_stack_schedules_completion_when_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pending = tmp_path / "tools" / "pending_launchers"
    pending.mkdir(parents=True)
    (pending / "DjGoo.exe").write_bytes(b"pending")
    helper = tmp_path / "tools" / "complete_launcher_update.py"
    helper.write_text("# helper\n", encoding="utf-8")
    pythonw = tmp_path / "runtime" / "python" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_bytes(b"python")

    calls: list[dict[str, object]] = []

    def popen(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return object()

    monkeypatch.setattr(portable_entry.subprocess, "Popen", popen)
    monkeypatch.setattr(
        portable_entry,
        "clean_subprocess_environment",
        lambda: {"CLEAN": "1"},
    )

    assert portable_entry.schedule_pending_launcher_completion(tmp_path) is True
    assert len(calls) == 1
    assert calls[0]["command"] == [
        str(pythonw),
        str(helper),
        "--root",
        str(tmp_path.resolve()),
    ]
    assert calls[0]["env"] == {"CLEAN": "1"}


def test_portable_stack_does_not_schedule_without_pending(
    tmp_path: Path,
) -> None:
    assert portable_entry.schedule_pending_launcher_completion(tmp_path) is False
