from __future__ import annotations

import sys
import threading
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, Tk, messagebox

import launcher.djgoo_voice_launcher as voice_launcher_base
from voice.discovery_connection import pair_from_invite_with_discovery


# Replace guessed-address pairing with recipient-led LAN discovery before the
# normal certificate-pinned direct/Discord/relay failover runs.
voice_launcher_base.pair_from_invite = pair_from_invite_with_discovery

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
from tools.windows_firewall import ensure_recipient_firewall


class DjGooVoiceExperience(VoiceRemoteLauncher):
    """Add explicit request timing to the secure recipient controller."""

    def __init__(self, root: Tk, project_root: Path) -> None:
        self._firewall_busy = False
        super().__init__(root, project_root)
        install_frozen_shutdown(self.root)
        self.root.after(400, self.ensure_local_link)

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

    def ensure_local_link(self) -> None:
        if self._firewall_busy:
            return
        self._firewall_busy = True
        self.log("Checking DjGoo Voice outbound firewall access…")
        threading.Thread(
            target=self._firewall_worker,
            name="djgoo-voice-firewall-repair",
            daemon=True,
        ).start()

    def _firewall_worker(self) -> None:
        executable = (
            Path(sys.executable).resolve()
            if bool(getattr(sys, "frozen", False))
            else None
        )
        try:
            success, detail = ensure_recipient_firewall(
                self.project_root,
                executable,
            )
        except Exception as exc:
            success, detail = False, f"{type(exc).__name__}: {exc}"
        try:
            self.root.after(
                0,
                lambda: self._finish_firewall_check(success, detail),
            )
        except Exception:
            pass

    def _finish_firewall_check(self, success: bool, detail: str) -> None:
        self._firewall_busy = False
        if success:
            if detail == "created":
                self.log(
                    "Windows Firewall now allows DjGoo Voice discovery and gateway traffic."
                )
            elif detail == "firewall-disabled":
                self.log("Windows Firewall is disabled; no recipient rule was required.")
            elif detail != "source-mode":
                self.log("DjGoo Voice firewall access is ready.")
            return
        self.log("Recipient firewall needs attention: " + detail)
        messagebox.showwarning(
            "DjGoo Voice Link",
            detail,
            parent=self.root,
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
