from __future__ import annotations

from types import SimpleNamespace

from tools import djgoo_stack


class FakeProcess:
    def __init__(self, pid: int, *, parents=(), cmdline=()):
        self.pid = pid
        self._parents = [SimpleNamespace(pid=value) for value in parents]
        self._cmdline = list(cmdline)

    def parents(self):
        return self._parents

    def cmdline(self):
        return self._cmdline


def test_heartbeat_accepts_verified_redbot_child(monkeypatch):
    child = FakeProcess(
        200,
        parents=(100,),
        cmdline=(str(djgoo_stack.PROJECT_ROOT / "tools" / "start_redbot_selector.py"),),
    )
    monkeypatch.setattr(djgoo_stack.psutil, "Process", lambda pid: child)

    assert djgoo_stack.heartbeat_pid_owned_by(100, 200) is True


def test_heartbeat_rejects_unrelated_or_wrong_command(monkeypatch):
    unrelated = FakeProcess(200, parents=(999,), cmdline=("start_redbot_selector.py",))
    monkeypatch.setattr(djgoo_stack.psutil, "Process", lambda pid: unrelated)
    assert djgoo_stack.heartbeat_pid_owned_by(100, 200) is False

    wrong_command = FakeProcess(200, parents=(100,), cmdline=("python.exe", "other.py"))
    monkeypatch.setattr(djgoo_stack.psutil, "Process", lambda pid: wrong_command)
    assert djgoo_stack.heartbeat_pid_owned_by(100, 200) is False
