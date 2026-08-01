from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import psutil

from tools import djgoo_portable_stack as adapter


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **fields: object) -> None:
        self.events.append((name, fields))


class HiddenSocketProcess:
    def __init__(
        self,
        pid: int,
        command: list[str],
        created: float,
        *,
        cwd: Path | None = None,
    ) -> None:
        self.pid = pid
        self._command = command
        self._created = created
        self._cwd = cwd
        self.terminated = False
        self.killed = False

    def cmdline(self) -> list[str]:
        return list(self._command)

    def cwd(self) -> str:
        if self._cwd is None:
            raise psutil.AccessDenied(self.pid)
        return str(self._cwd)

    def create_time(self) -> float:
        return self._created

    def net_connections(self, *, kind: str):
        assert kind == "tcp"
        raise psutil.AccessDenied(self.pid)

    def children(self, *, recursive: bool):
        assert recursive is True
        return []

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def is_running(self) -> bool:
        return not self.terminated and not self.killed


def _audio_dir(root: Path) -> Path:
    return root / "data" / "discordbot" / "cogs" / "Audio"


def _command(root: Path) -> list[str]:
    return [
        "java.exe",
        "-Xms64M",
        "-jar",
        str(_audio_dir(root) / "Lavalink.jar"),
    ]


def _relative_command() -> list[str]:
    return ["java.exe", "-Xms64M", "-jar", "Lavalink.jar"]


def test_reachable_port_adopts_oldest_matching_process_when_socket_owner_is_hidden(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path.resolve()
    listener = HiddenSocketProcess(1001, _command(root), created=10.0)
    failed_bind_attempt = HiddenSocketProcess(1002, _command(root), created=20.0)
    monkeypatch.setattr(adapter.psutil, "process_iter", lambda: [failed_bind_attempt, listener])
    monkeypatch.setattr(adapter, "_lavalink_port_ready", lambda timeout=0.4: True)
    monkeypatch.setattr(adapter.psutil, "wait_procs", lambda targets, timeout: (targets, []))

    records: dict[str, dict[str, object]] = {}
    logger = RecordingLogger()
    core = SimpleNamespace(
        PROJECT_ROOT=root,
        LOG=logger,
        write_component_record=lambda spec, process: records.__setitem__(
            spec.name,
            {"pid": process.pid, "create_time": process.create_time()},
        ),
    )
    spec = SimpleNamespace(
        name="lavalink",
        command_markers=("lavalink.jar", str(root)),
    )

    assert adapter._adopt_lavalink_listener(core, spec) is True
    assert records["lavalink"]["pid"] == listener.pid
    assert failed_bind_attempt.terminated is True
    adopted = [fields for name, fields in logger.events if name == "component.adopted"]
    assert adopted[-1]["reason"] == "reachable-lavalink-fallback"


def test_relative_managed_lavalink_is_recognized_by_audio_working_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    managed = HiddenSocketProcess(
        1501,
        _relative_command(),
        created=5.0,
        cwd=_audio_dir(root),
    )

    assert adapter._process_is_package_lavalink(managed, root) is True

    unrelated = HiddenSocketProcess(
        1502,
        _relative_command(),
        created=6.0,
        cwd=root / "unrelated",
    )
    assert adapter._process_is_package_lavalink(unrelated, root) is False


def test_relative_managed_listener_is_adopted_and_new_failed_bind_is_removed(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path.resolve()
    managed_listener = HiddenSocketProcess(
        1601,
        _relative_command(),
        created=5.0,
        cwd=_audio_dir(root),
    )
    failed_bind_attempt = HiddenSocketProcess(1602, _command(root), created=20.0)
    monkeypatch.setattr(
        adapter.psutil,
        "process_iter",
        lambda: [failed_bind_attempt, managed_listener],
    )
    monkeypatch.setattr(adapter, "_lavalink_port_ready", lambda timeout=0.4: True)
    monkeypatch.setattr(adapter.psutil, "wait_procs", lambda targets, timeout: (targets, []))

    records: dict[str, dict[str, object]] = {}
    core = SimpleNamespace(
        PROJECT_ROOT=root,
        LOG=RecordingLogger(),
        write_component_record=lambda spec, process: records.__setitem__(
            spec.name,
            {"pid": process.pid, "create_time": process.create_time()},
        ),
    )
    spec = SimpleNamespace(name="lavalink", command_markers=("lavalink.jar", str(root)))

    assert adapter._adopt_lavalink_listener(core, spec) is True
    assert records["lavalink"]["pid"] == managed_listener.pid
    assert failed_bind_attempt.terminated is True


def test_fallback_readiness_belongs_only_to_oldest_matching_process(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path.resolve()
    listener = HiddenSocketProcess(2001, _command(root), created=10.0)
    failed_bind_attempt = HiddenSocketProcess(2002, _command(root), created=20.0)
    processes = {listener.pid: listener, failed_bind_attempt.pid: failed_bind_attempt}
    monkeypatch.setattr(adapter.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(adapter.psutil, "process_iter", lambda: [failed_bind_attempt, listener])
    monkeypatch.setattr(adapter, "_lavalink_port_ready", lambda timeout=0.4: True)

    records = {
        "lavalink": {
            "pid": listener.pid,
            "create_time": listener.create_time(),
        }
    }
    core = SimpleNamespace(
        PROJECT_ROOT=root,
        component_record=lambda name: records.get(name),
    )

    assert adapter._portable_lavalink_ready(core) is True

    records["lavalink"] = {
        "pid": failed_bind_attempt.pid,
        "create_time": failed_bind_attempt.create_time(),
    }
    assert adapter._portable_lavalink_ready(core) is False
