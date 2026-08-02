from __future__ import annotations

from launcher import frozen_shutdown


class FakeRoot:
    def __init__(self) -> None:
        self.protocols = {}
        self.quit_calls = 0
        self.destroy_calls = 0

    def protocol(self, name, callback) -> None:
        self.protocols[name] = callback

    def quit(self) -> None:
        self.quit_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1


def test_non_frozen_shutdown_is_idempotent() -> None:
    root = FakeRoot()
    close = frozen_shutdown.install_frozen_shutdown(root, frozen=False)

    assert root.protocols["WM_DELETE_WINDOW"] is close
    root.destroy()
    root.destroy()

    assert root.quit_calls == 1
    assert root.destroy_calls == 1


def test_frozen_shutdown_uses_immediate_clean_exit(monkeypatch) -> None:
    root = FakeRoot()
    exits: list[int] = []
    monkeypatch.setattr(
        frozen_shutdown.os,
        "_exit",
        lambda code: exits.append(code),
    )

    close = frozen_shutdown.install_frozen_shutdown(root, frozen=True)
    close()

    assert root.quit_calls == 1
    assert root.destroy_calls == 1
    assert exits == [0]
