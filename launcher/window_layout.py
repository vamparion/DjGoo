from __future__ import annotations

from tkinter import Tk


def fit_window_to_content(
    root: Tk,
    *,
    minimum_width: int,
    minimum_height: int,
    screen_margin: int = 36,
) -> None:
    """Size a simple control window to its real content without scrollbars.

    Tk's requested size includes the user's DPI scaling.  Clamping that size to
    the usable screen keeps Host and recipient controls visible on first open
    instead of requiring the user to drag the window larger.
    """

    root.update_idletasks()
    screen_width = max(640, int(root.winfo_screenwidth()))
    screen_height = max(480, int(root.winfo_screenheight()))
    requested_width = max(int(minimum_width), int(root.winfo_reqwidth()))
    requested_height = max(int(minimum_height), int(root.winfo_reqheight()))
    width = min(requested_width, max(640, screen_width - int(screen_margin)))
    height = min(requested_height, max(480, screen_height - int(screen_margin)))
    root.geometry(f"{width}x{height}")
    root.minsize(min(int(minimum_width), width), min(int(minimum_height), height))
