from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from tools import djgoo_portable_stack as adapter


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **fields: object) -> None:
        self.events.append((name, fields))


def make_fake_core() -> SimpleNamespace:
    logger = RecordingLogger()
    return SimpleNamespace(
        Logger=lambda: logger,
        start_component=lambda spec, *, resume_playback=False: True,
        run_supervisor=lambda: 0,
        control_request=lambda action, timeout=0.35: {"ok": True},
        WINDOWS_DETACHED_FLAGS=0,
        LOG=logger,
    )


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_configure_core_uses_bundled_runtimes_and_safe_flags(tmp_path, monkeypatch) -> None:
    runtime_python = touch(tmp_path / "runtime" / "python" / "python.exe")
    runtime_pythonw = touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    runtime_java = touch(tmp_path / "runtime" / "java" / "bin" / "java.exe")
    monkeypatch.setenv("DJGOO_JAVA", r"C:\stale-djgoo\java.exe")

    core = adapter.configure_core(make_fake_core(), tmp_path)

    assert core.PROJECT_ROOT == tmp_path.resolve()
    assert core.BOT_PYTHON == runtime_python
    assert core.VOICE_PYTHON == runtime_python
    assert core.PYTHONW == runtime_pythonw
    assert core.JAVA == runtime_java
    assert callable(core.spawn_supervisor)

    if os.name == "nt":
        assert core.WINDOWS_DETACHED_FLAGS & subprocess.DETACHED_PROCESS
        assert core.WINDOWS_DETACHED_FLAGS & subprocess.CREATE_NEW_PROCESS_GROUP
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        assert not breakaway or not (core.WINDOWS_DETACHED_FLAGS & breakaway)
    else:
        assert core.WINDOWS_DETACHED_FLAGS == 0


def test_spawn_supervisor_reenters_through_portable_adapter(tmp_path, monkeypatch) -> None:
    pythonw = touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    python = touch(tmp_path / "runtime" / "python" / "python.exe")
    calls: list[dict[str, object]] = []

    def fake_popen(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(adapter.subprocess, "Popen", fake_popen)
    core = SimpleNamespace(
        PYTHONW=pythonw,
        BOT_PYTHON=python,
        COMPONENT_LOG_DIR=tmp_path / "logs" / "components",
        PROJECT_ROOT=tmp_path,
        WINDOWS_DETACHED_FLAGS=adapter.portable_windows_flags(),
        control_request=lambda action, timeout=0.35: {"ok": True},
        LOG=RecordingLogger(),
    )

    assert adapter.spawn_portable_supervisor(core) is True
    assert len(calls) == 1
    command = calls[0]["command"]
    assert command == [str(pythonw), str(Path(adapter.__file__).resolve()), "supervise"]
    assert calls[0]["cwd"] == str(tmp_path)


def test_component_launch_errors_are_logged_instead_of_crashing(tmp_path) -> None:
    touch(tmp_path / "runtime" / "python" / "python.exe")
    touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    touch(tmp_path / "runtime" / "java" / "bin" / "java.exe")
    logger = RecordingLogger()

    def failing_start(spec, *, resume_playback=False):
        raise OSError(87, "The parameter is incorrect")

    core = SimpleNamespace(
        Logger=lambda: logger,
        start_component=failing_start,
        run_supervisor=lambda: 0,
        control_request=lambda action, timeout=0.35: {"ok": True},
        WINDOWS_DETACHED_FLAGS=0,
        LOG=logger,
    )
    configured = adapter.configure_core(core, tmp_path)

    spec = SimpleNamespace(name="lavalink", command=["java.exe"])
    assert configured.start_component(spec) is False
    assert logger.events[-1][0] == "component.start_failed"
    assert "parameter is incorrect" in str(logger.events[-1][1]["error"]).lower()
