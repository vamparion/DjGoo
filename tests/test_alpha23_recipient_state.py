from __future__ import annotations

import json
from pathlib import Path

from launcher import window_layout
from launcher.djgoo_voice_experience import DjGooVoiceExperience
from launcher.djgoo_voice_launcher import VoiceRemoteLauncher
from tools import supervisor_lifecycle


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_pairing_poll_does_not_reset_visible_status(monkeypatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        VoiceRemoteLauncher,
        "refresh_status",
        lambda self: called.append(True),
    )
    experience = object.__new__(DjGooVoiceExperience)
    experience._pairing_busy = True

    experience.refresh_status()

    assert called == []


def test_current_supervisor_is_not_restarted_for_timestamp_order(
    tmp_path,
    monkeypatch,
) -> None:
    version = "0.3.0-alpha.23"
    _write_json(
        tmp_path / "data" / "pids" / "supervisor.json",
        {"pid": 808, "version": version},
    )
    _write_json(
        tmp_path / "data" / "djgoo-supervisor-state.json",
        {
            "supervisor_pid": 808,
            "desired_running": True,
            "supervisor_version": version,
            "supervisor_contract": supervisor_lifecycle.EXPECTED_SUPERVISOR_CONTRACT,
            "started_at": 100.0,
        },
    )
    _write_json(
        tmp_path / "data" / "installed-version.json",
        {"version": version, "installed_at": 200.0},
    )
    monkeypatch.setattr(
        supervisor_lifecycle,
        "live_supervisor_state",
        lambda: None,
    )
    monkeypatch.setattr(
        supervisor_lifecycle,
        "process_exists",
        lambda pid: pid == 808,
    )
    monkeypatch.setattr(
        supervisor_lifecycle.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a current supervisor must not be shut down")
        ),
    )

    changed = supervisor_lifecycle.restart_stale_supervisor(
        tmp_path,
        installed_version=version,
        runtime_python=tmp_path / "python.exe",
        runtime_pythonw=tmp_path / "pythonw.exe",
        stack_script=tmp_path / "djgoo_stack.py",
        environment={},
        log=lambda _message: None,
    )

    assert changed is False


class _FakeRoot:
    def __init__(self) -> None:
        self.geometry_value = ""
        self.minimum = (0, 0)

    def update_idletasks(self) -> None:
        pass

    def winfo_reqwidth(self) -> int:
        return 1200

    def winfo_reqheight(self) -> int:
        return 1100

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def geometry(self, value: str) -> None:
        self.geometry_value = value

    def minsize(self, width: int, height: int) -> None:
        self.minimum = (width, height)


def test_window_uses_taskbar_excluding_work_area(monkeypatch) -> None:
    root = _FakeRoot()
    monkeypatch.setattr(
        window_layout,
        "usable_work_area",
        lambda _root: (0, 0, 1920, 1000),
    )

    window_layout.fit_window_to_content(
        root,
        minimum_width=900,
        minimum_height=690,
    )

    width, height, x, y = map(
        int,
        root.geometry_value.replace("+", "x").split("x"),
    )
    assert width <= 1884
    assert height <= 944
    assert x >= 0
    assert y >= 0
    assert y + height + 40 <= 1000
