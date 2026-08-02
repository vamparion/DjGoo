from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from tkinter import Tk


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def usable_work_area(root: Tk) -> tuple[int, int, int, int]:
    """Return the desktop work area, excluding the Windows taskbar."""

    if os.name == "nt":
        rect = _Rect()
        try:
            if ctypes.windll.user32.SystemParametersInfoW(
                0x0030,  # SPI_GETWORKAREA
                0,
                ctypes.byref(rect),
                0,
            ):
                width = int(rect.right - rect.left)
                height = int(rect.bottom - rect.top)
                if width > 0 and height > 0:
                    return (
                        int(rect.left),
                        int(rect.top),
                        int(rect.right),
                        int(rect.bottom),
                    )
        except (AttributeError, OSError):
            pass
    return (
        0,
        0,
        max(640, int(root.winfo_screenwidth())),
        max(480, int(root.winfo_screenheight())),
    )


def fit_window_to_content(
    root: Tk,
    *,
    minimum_width: int,
    minimum_height: int,
    screen_margin: int = 36,
) -> None:
    """Fit the client window inside the usable desktop, never behind the taskbar."""

    root.update_idletasks()
    left, top, right, bottom = usable_work_area(root)
    work_width = max(640, right - left)
    work_height = max(480, bottom - top)
    requested_width = max(int(minimum_width), int(root.winfo_reqwidth()))
    requested_height = max(int(minimum_height), int(root.winfo_reqheight()))

    # Tk geometry describes the client area, while Windows adds the title bar
    # and resize frame outside it. Reserve enough work-area space for those
    # decorations as well as a small visible border on every side.
    horizontal_reserve = max(24, int(screen_margin))
    vertical_reserve = max(56, int(screen_margin) + 20)
    width = min(
        requested_width,
        max(640, work_width - horizontal_reserve),
    )
    height = min(
        requested_height,
        max(480, work_height - vertical_reserve),
    )
    outer_width = min(work_width, width + 16)
    outer_height = min(work_height, height + 40)
    x = left + max(0, (work_width - outer_width) // 2)
    y = top + max(0, (work_height - outer_height) // 2)

    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(
        min(int(minimum_width), width),
        min(int(minimum_height), height),
    )
