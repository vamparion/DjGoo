from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools import supervisor_lifecycle


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_matching_supervisor_version_is_left_running(tmp_path, monkeypatch) -> None:
    write_json(
        tmp_path / "data" / "pids" / "supervisor.json",
        {"pid": 101, "version": "0.3.0-alpha.9"},
    )
    write_json(
        tmp_path / "data" / "djgoo-supervisor-state.json",
        {"supervisor_pid": 101, "desired_running": True, "supervisor_version": "0.3.0-alpha.9"},
    )
    monkeypatch.setattr(supervisor_lifecycle, "process_exists", lambda pid: pid == 101)
    monkeypatch.setattr(
        supervisor_lifecycle.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not shut down")),
    )

    changed = supervisor_lifecycle.restart_stale_supervisor(
        tmp_path,
        installed_version="0.3.0-alpha.9",
        runtime_python=tmp_path / "python.exe",
        runtime_pythonw=tmp_path / "pythonw.exe",
        stack_script=tmp_path / "djgoo_stack.py",
        environment={},
        log=lambda _message: None,
    )

    assert changed is False


def test_pre_versioned_supervisor_is_shutdown_and_restarted(tmp_path, monkeypatch) -> None:
    write_json(tmp_path / "data" / "pids" / "supervisor.json", {"pid": 202})
    write_json(
        tmp_path / "data" / "djgoo-supervisor-state.json",
        {"supervisor_pid": 202, "desired_running": True},
    )
    alive = {202: True}
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(supervisor_lifecycle, "process_exists", lambda pid: alive.get(pid, False))

    def fake_run(command, **kwargs):
        calls.append(("run", list(command)))
        alive[202] = False
        return SimpleNamespace(returncode=0)

    def fake_popen(command, **kwargs):
        calls.append(("popen", list(command)))
        return SimpleNamespace(pid=303)

    monkeypatch.setattr(supervisor_lifecycle.subprocess, "run", fake_run)
    monkeypatch.setattr(supervisor_lifecycle.subprocess, "Popen", fake_popen)
    messages: list[str] = []

    changed = supervisor_lifecycle.restart_stale_supervisor(
        tmp_path,
        installed_version="0.3.0-alpha.9",
        runtime_python=tmp_path / "python.exe",
        runtime_pythonw=tmp_path / "pythonw.exe",
        stack_script=tmp_path / "tools" / "djgoo_stack.py",
        environment={"DJGOO": "1"},
        log=messages.append,
    )

    assert changed is True
    assert calls[0][0] == "run"
    assert calls[0][1][-1] == "shutdown"
    assert calls[1][0] == "popen"
    assert calls[1][1][-1] == "start"
    assert not (tmp_path / "data" / "pids" / "supervisor.json").exists()
    assert not (tmp_path / "data" / "djgoo-supervisor-state.json").exists()
    assert any("pre-versioned" in message for message in messages)


def test_stale_stopped_supervisor_is_not_restarted(tmp_path, monkeypatch) -> None:
    write_json(
        tmp_path / "data" / "pids" / "supervisor.json",
        {"pid": 404, "version": "0.3.0-alpha.8"},
    )
    write_json(
        tmp_path / "data" / "djgoo-supervisor-state.json",
        {"supervisor_pid": 404, "desired_running": False, "supervisor_version": "0.3.0-alpha.8"},
    )
    alive = {404: True}
    monkeypatch.setattr(supervisor_lifecycle, "process_exists", lambda pid: alive.get(pid, False))

    def fake_run(command, **kwargs):
        alive[404] = False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(supervisor_lifecycle.subprocess, "run", fake_run)
    monkeypatch.setattr(
        supervisor_lifecycle.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must remain stopped")),
    )

    assert supervisor_lifecycle.restart_stale_supervisor(
        tmp_path,
        installed_version="0.3.0-alpha.9",
        runtime_python=tmp_path / "python.exe",
        runtime_pythonw=tmp_path / "pythonw.exe",
        stack_script=tmp_path / "djgoo_stack.py",
        environment={},
        log=lambda _message: None,
    ) is True
