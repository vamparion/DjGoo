from __future__ import annotations

import os
import sys
from typing import Any, Callable


def install_frozen_shutdown(
    root: Any,
    *,
    frozen: bool | None = None,
) -> Callable[[], None]:
    """Make Tk shutdown deterministic for PyInstaller one-file launchers.

    PyInstaller's parent bootloader can only remove its temporary ``_MEI``
    directory after the Python child has fully exited. Tk callbacks and daemon
    workers can otherwise keep interpreter finalization alive long enough for
    Windows to display the bootloader cleanup error.
    """

    should_force_exit = bool(
        getattr(sys, "frozen", False) if frozen is None else frozen
    )
    original_destroy = root.destroy
    state = {"closing": False}

    def close() -> None:
        if state["closing"]:
            return
        state["closing"] = True
        try:
            root.quit()
        except Exception:
            pass
        try:
            original_destroy()
        except Exception:
            pass
        if should_force_exit:
            os._exit(0)

    root.protocol("WM_DELETE_WINDOW", close)
    root.destroy = close
    return close
