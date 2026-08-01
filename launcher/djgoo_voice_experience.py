from __future__ import annotations

from tkinter import LEFT, X, Frame, Label, Tk

from launcher.djgoo_voice_launcher import (
    ACCENT_2,
    MUTED,
    PANEL,
    TEXT,
    VoiceRemoteLauncher,
    application_root,
)


class DjGooVoiceExperience(VoiceRemoteLauncher):
    """Add explicit request timing to the secure recipient controller."""

    def _build(self) -> None:
        super()._build()
        timing = Frame(
            self.root,
            bg=PANEL,
            padx=18,
            pady=10,
        )
        timing.pack(
            fill=X,
            padx=20,
            pady=(0, 10),
            before=self.activity,
        )
        Label(
            timing,
            text="REQUEST TIMING",
            font=("Segoe UI", 8, "bold"),
            bg=PANEL,
            fg=ACCENT_2,
        ).pack(side=LEFT)
        Label(
            timing,
            text="Type the song above, then choose:",
            font=("Segoe UI", 9),
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT, padx=(10, 10))
        self._button(
            timing,
            "Next",
            lambda: self.send_timed_request("next"),
            accent=True,
        ).pack(side=LEFT, padx=(0, 6))
        self._button(
            timing,
            "Now",
            lambda: self.send_timed_request("now"),
            danger=True,
        ).pack(side=LEFT, padx=(0, 6))
        self._button(
            timing,
            "Later",
            lambda: self.send_timed_request("later"),
        ).pack(side=LEFT)

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
