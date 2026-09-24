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


class FakeConnection:
    def __init__(self, port: int, status: str = "LISTEN") -> None:
        self.laddr = ("::1", port)
        self.status = status


class FakeProcess:
    def __init__(
        self,
        pid: int,
        command: list[str],
        *,
        created: float = 100.0,
        listening_port: int | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.pid = pid
        self._command = command
        self._created = created
        self._listening_port = listening_port
        self._cwd = cwd
        self.terminated = False
        self.killed = False

    def cmdline(self) -> list[str]:
        return list(self._command)

    def create_time(self) -> float:
        return self._created

    def cwd(self) -> str:
        if self._cwd is None:
            raise OSError("cwd unavailable")
        return str(self._cwd)

    def net_connections(self, *, kind: str) -> list[FakeConnection]:
        assert kind == "tcp"
        if self._listening_port is None:
            return []
        return [FakeConnection(self._listening_port)]

    def children(self, *, recursive: bool) -> list[FakeProcess]:
        assert recursive is True
        return []

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def is_running(self) -> bool:
        return not self.terminated and not self.killed


def make_fake_core() -> SimpleNamespace:
    logger = RecordingLogger()
    records: dict[str, dict[str, object]] = {}
    core = SimpleNamespace()
    core.Logger = lambda: logger
    core.LOG = logger
    core.WINDOWS_DETACHED_FLAGS = 0
    core.control_request = lambda action, timeout=0.35: {"ok": True}
    core.component_running = lambda spec: False
    core.terminate_component = lambda spec, reason: None
    core.component_environment = lambda resume_playback=False: {"BASE": "1"}
    core.start_component = lambda spec, *, resume_playback=False: True
    core.run_supervisor = lambda: 0
    core.component_record = lambda name: records.get(name)
    core.read_json = lambda path: None
    core.health_path = lambda name: Path(f"{name}.health.json")
    core.pid_path = lambda name: Path(f"{name}.pid.json")
    core.write_component_record = lambda spec, process: records.__setitem__(
        spec.name,
        {
            "pid": int(process.pid),
            "create_time": float(process.create_time()),
        },
    )
    core._records = records
    return core


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
        assert core.WINDOWS_DETACHED_FLAGS & subprocess.CREATE_NO_WINDOW
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


def test_component_launch_errors_are_logged_instead_of_crashing(tmp_path, monkeypatch) -> None:
    touch(tmp_path / "runtime" / "python" / "python.exe")
    touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    touch(tmp_path / "runtime" / "java" / "bin" / "java.exe")
    core = make_fake_core()

    def failing_start(spec, *, resume_playback=False):
        raise OSError(87, "The parameter is incorrect")

    core.start_component = failing_start
    configured = adapter.configure_core(core, tmp_path)
    monkeypatch.setattr(adapter, "_processes_listening_on", lambda _port: [])

    spec = SimpleNamespace(name="lavalink", command=["java.exe"])
    assert configured.start_component(spec) is False
    assert configured.LOG.events[-1][0] == "component.start_failed"
    assert "parameter is incorrect" in str(configured.LOG.events[-1][1]["error"]).lower()


def test_child_process_receives_explicit_component_identity(tmp_path) -> None:
    touch(tmp_path / "runtime" / "python" / "python.exe")
    touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    touch(tmp_path / "runtime" / "java" / "bin" / "java.exe")
    core = make_fake_core()
    observed: dict[str, str] = {}

    def capture_environment(spec, *, resume_playback=False):
        observed.update(core.component_environment(resume_playback=resume_playback))
        return True

    core.start_component = capture_environment
    configured = adapter.configure_core(core, tmp_path)

    assert configured.start_component(SimpleNamespace(name="redbot", command=[])) is True
    assert observed["DJGOO_COMPONENT_NAME"] == "redbot"


def test_existing_lavalink_listener_is_adopted_by_supervisor(tmp_path, monkeypatch) -> None:
    root = tmp_path.resolve()
    listener = FakeProcess(
        4321,
        ["java.exe", "-jar", str(root / "data" / "discordbot" / "cogs" / "Audio" / "Lavalink.jar")],
        listening_port=adapter.LAVALINK_PORT,
    )
    monkeypatch.setattr(adapter.psutil, "process_iter", lambda: [listener])

    core = adapter.configure_core(make_fake_core(), root)
    spec = SimpleNamespace(
        name="lavalink",
        command_markers=("lavalink.jar", str(root)),
    )

    assert core.component_running(spec) is True
    assert core._records["lavalink"]["pid"] == listener.pid
    assert any(name == "component.adopted" for name, _ in core.LOG.events)


def test_lavalink_readiness_is_bound_to_recorded_listener(tmp_path, monkeypatch) -> None:
    root = tmp_path.resolve()
    listener = FakeProcess(
        6789,
        ["java.exe", "-jar", str(root / "data" / "discordbot" / "cogs" / "Audio" / "Lavalink.jar")],
        created=55.0,
        listening_port=adapter.LAVALINK_PORT,
    )
    monkeypatch.setattr(adapter.psutil, "Process", lambda pid: listener)
    core = make_fake_core()
    core.PROJECT_ROOT = root
    core._records["lavalink"] = {"pid": listener.pid, "create_time": listener.create_time()}

    assert adapter._portable_lavalink_ready(core) is True
    listener._listening_port = None
    monkeypatch.setattr(adapter, "_lavalink_port_ready", lambda timeout=0.4: False)
    assert adapter._portable_lavalink_ready(core) is False


def test_initial_redbot_ready_event_gets_bounded_startup_grace(monkeypatch) -> None:
    core = make_fake_core()
    core._records["redbot"] = {"pid": 101}
    heartbeat = {
        "pid": 101,
        "timestamp": 970.0,
        "ready": True,
        "event": "redbot.ready",
        "audio_loaded": True,
        "discord_ready": True,
    }
    core.read_json = lambda path: heartbeat
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)
    monkeypatch.setattr(adapter, "_portable_lavalink_ready", lambda _core: True)
    monkeypatch.setattr(adapter, "_lavalink_client_ready", lambda _core, _pid: True)

    assert adapter._portable_redbot_ready(core) is True
    heartbeat["event"] = "redbot.heartbeat"
    assert adapter._portable_redbot_ready(core) is False


def test_supervisor_starts_lavalink_as_real_component(tmp_path, monkeypatch) -> None:
    touch(tmp_path / "runtime" / "python" / "python.exe")
    touch(tmp_path / "runtime" / "python" / "pythonw.exe")
    touch(tmp_path / "runtime" / "java" / "bin" / "java.exe")
    core = make_fake_core()
    started: list[str] = []

    def record_start(spec, *, resume_playback=False):
        started.append(spec.name)
        return True

    core.start_component = record_start
    configured = adapter.configure_core(core, tmp_path)
    monkeypatch.setattr(adapter, "_processes_listening_on", lambda _port: [])
    spec = SimpleNamespace(name="lavalink", command=["java.exe"])

    assert configured.start_component(spec) is True
    assert started == ["lavalink"]
    assert configured.component_running(
        SimpleNamespace(name="lavalink", command_markers=("lavalink.jar", str(tmp_path)))
    ) is False


def test_lavalink_start_adopts_existing_listener_before_spawning(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path.resolve()
    listener = FakeProcess(
        2468,
        ["java.exe", "-jar", str(root / "data" / "discordbot" / "cogs" / "Audio" / "Lavalink.jar")],
        listening_port=adapter.LAVALINK_PORT,
    )
    monkeypatch.setattr(adapter.psutil, "process_iter", lambda: [listener])
    core = make_fake_core()
    started: list[str] = []
    core.start_component = lambda spec, *, resume_playback=False: started.append(spec.name) or True
    configured = adapter.configure_core(core, root)

    assert configured.start_component(SimpleNamespace(name="lavalink", command=[])) is True
    assert started == []
    assert configured._records["lavalink"]["pid"] == listener.pid


def test_lavalink_start_reports_foreign_port_owner_instead_of_spawning(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path.resolve()
    foreign = FakeProcess(
        1357,
        ["java.exe", "-jar", r"C:\OtherDjGoo\data\discordbot\cogs\Audio\Lavalink.jar"],
        listening_port=adapter.LAVALINK_PORT,
        cwd=Path(r"C:\OtherDjGoo\data\discordbot\cogs\Audio"),
    )
    monkeypatch.setattr(adapter.psutil, "process_iter", lambda: [foreign])
    core = make_fake_core()
    started: list[str] = []
    core.start_component = lambda spec, *, resume_playback=False: started.append(spec.name) or True
    configured = adapter.configure_core(core, root)

    assert configured.start_component(SimpleNamespace(name="lavalink", command=[])) is False
    assert started == []
    assert configured.LOG.events[-1][0] == "component.port_in_use"
