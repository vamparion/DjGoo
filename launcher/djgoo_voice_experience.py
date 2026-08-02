from __future__ import annotations

from pathlib import Path
from tkinter import LEFT, X, Frame, Label, Tk

from launcher.djgoo_voice_launcher import (
    ACCENT_2,
    MUTED,
    PANEL,
    TEXT,
    VoiceRemoteLauncher,
    application_root,
)
from launcher.frozen_shutdown import install_frozen_shutdown
from launcher.window_layout import fit_window_to_content


class DjGooVoiceExperience(VoiceRemoteLauncher):
    """Add explicit request timing to the secure recipient controller."""

    def __init__(self, root: Tk, project_root: Path) -> None:
        super().__init__(root, project_root)
        install_frozen_shutdown(self.root)

    def _build(self) -> None:
        super()._build()
        self.activity.configure(height=4)
        timing = Frame(
            self.root,
            bg=PANEL,
            padx=14,
            pady=8,
        )
        timing.pack(
            fill=X,
            padx=20,
            pady=(0, 8),
            before=self.activity,
        )
        Label(
            timing,
            text="REQUEST",
            font=("Segoe UI", 8, "bold"),
            bg=PANEL,
            fg=ACCENT_2,
        ).pack(side=LEFT)
        Label(
            timing,
            text="Use the song box above, then:",
            font=("Segoe UI", 9),
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT, padx=(9, 9))
        self._button(
            timing,
            "Next",
            lambda: self.send_timed_request("next"),
            accent=True,
        ).pack(side=LEFT, padx=(0, 5))
        self._button(
            timing,
            "Now",
            lambda: self.send_timed_request("now"),
            danger=True,
        ).pack(side=LEFT, padx=(0, 5))
        self._button(
            timing,
            "Later",
            lambda: self.send_timed_request("later"),
        ).pack(side=LEFT)
        self.root.after_idle(
            lambda: fit_window_to_content(
                self.root,
                minimum_width=900,
                minimum_height=690,
            )
        )

    def send_timed_request(self, timing: str) -> None:
        query = self.request.get().strip()
        if not query:
            return
        self.request.set("")
        if timing == "now":
            self.send_phrase(f"play now {query}")
        elif timing == "later":
            self.send_phrase(f"queue request {query}")
        else:
            self.send_phrase(f"play next {query}")


def main() -> int:
    root = Tk()
    DjGooVoiceExperience(root, application_root())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
