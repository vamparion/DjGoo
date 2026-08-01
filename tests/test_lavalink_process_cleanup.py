from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import psutil

from tools import lavalink_process


class FakeAddress:
    def __init__(self, port: int) -> None:
        self.port = port


class FakeConnection:
    def __init__(self, pid: int, port: int, status: str = "LISTEN") -> None:
        self.pid = pid
        self.laddr = FakeAddress(port)
        self.status = status


class FakeProcess:
    def __init__(
        self,
        pid: int,
        *,
        name: str = "java.exe",
        command: list[str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.pid = pid
        self._name = name
        self._command = list(command or [])
        self._cwd = cwd
        self.terminated = False
        self.killed = False

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        return list(self._command)

    def cwd(self) -> str:
        if self._cwd is None:
            raise psutil.AccessDenied(self.pid)
        return str(self._cwd)

    def children(self, recursive: bool) -> list[FakeProcess]:
        assert recursive is True
        return []

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def is_running(self) -> bool:
        return not self.terminated and not self.killed


def test_system_listener_table_resolves_port_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        lavalink_process.psutil,
        "net_connections",
        lambda kind: [
            FakeConnection(101, lavalink_process.LAVALINK_PORT),
            FakeConnection(202, 9999),
        ],
    )
    monkeypatch.setattr(lavalink_process.os, "name", "posix")

    assert lavalink_process.listener_owner_pids() == [101]


def test_cleanup_stops_java_owner_even_when_command_and_cwd_are_hidden(
    tmp_path: Path, monkeypatch
) -> None:
    owner = FakeProcess(303, name="java.exe")
    processes = {owner.pid: owner}
    monkeypatch.setattr(lavalink_process, "listener_owner_pids", lambda port=2333: [owner.pid])
    monkeypatch.setattr(lavalink_process.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(lavalink_process.psutil, "process_iter", lambda: [])
    monkeypatch.setattr(
        lavalink_process.psutil,
        "wait_procs",
        lambda targets, timeout: (targets, []),
    )

    assert lavalink_process.cleanup_lavalink_processes(tmp_path) == [owner.pid]
    assert owner.terminated is True


def test_cleanup_also_removes_relative_command_package_process(
    tmp_path: Path, monkeypatch
) -> None:
    audio_dir = (
        tmp_path
        / "data"
        / "discordbot"
        / "cogs"
        / "Audio"
    ).resolve()
    process = FakeProcess(
        404,
        command=["java.exe", "-jar", "Lavalink.jar"],
        cwd=audio_dir,
    )
    monkeypatch.setattr(lavalink_process, "listener_owner_pids", lambda port=2333: [])
    monkeypatch.setattr(lavalink_process.psutil, "process_iter", lambda: [process])
    monkeypatch.setattr(
        lavalink_process.psutil,
        "wait_procs",
        lambda targets, timeout: (targets, []),
    )

    assert lavalink_process.cleanup_lavalink_processes(tmp_path) == [process.pid]
    assert process.terminated is True
