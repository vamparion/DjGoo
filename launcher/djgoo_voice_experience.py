from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, Tk, messagebox

import launcher.djgoo_voice_launcher as voice_launcher_base
from voice.connection_manager import load_recipient_credential
from voice.discovery_connection import pair_from_invite_with_discovery
from voice.pairing_bundle import parse_invite


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
    """Add explicit request timing and reliable pairing state to the recipient."""

    def __init__(self, root: Tk, project_root: Path) -> None:
        self._firewall_busy = False
        self._pairing_busy = False
        self._pairing_panel = None
        super().__init__(root, project_root)
        install_frozen_shutdown(self.root)
        self.root.after(400, self.ensure_local_link)

    @staticmethod
    def _walk_widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from DjGooVoiceExperience._walk_widgets(child)

    def _find_pairing_panel(self):
        for widget in self.root.winfo_children():
            if widget.winfo_class() != "Frame":
                continue
            for child in widget.winfo_children():
                try:
                    text = str(child.cget("text"))
                except Exception:
                    continue
                if text == "Connect this player":
                    return widget
        return None

    def _set_pairing_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._walk_widgets(self.root):
            if widget.winfo_class() != "Button":
                continue
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def _build(self) -> None:
        super()._build()
        self._pairing_panel = self._find_pairing_panel()
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

    def pair(self) -> None:
        if self._pairing_busy:
            self.log("Secure pairing is already in progress.")
            return
        raw_invite = self.invite.get().strip()
        try:
            invite = parse_invite(raw_invite)
        except Exception as exc:
            messagebox.showerror(
                "DjGoo Voice",
                str(exc),
                parent=self.root,
            )
            return

        device_name = self.device_name.get().strip() or "DjGoo Voice"
        self._pairing_busy = True
        self._set_pairing_buttons_enabled(False)
        self.status.set("Connecting through encrypted outbound route…")
        self.security.set(
            f"Safety number {invite.safety_number()} • "
            f"{len(invite.endpoints)} secure path(s) • pairing in progress"
        )
        self.log(
            "Secure pairing started. Controls will unlock after the protected "
            "device credential is written and verified."
        )

        def work() -> None:
            try:
                credential, transport = asyncio.run(
                    voice_launcher_base.pair_from_invite(
                        invite,
                        device_name=device_name,
                        credential_path=self.credential_path,
                    )
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda problem=exc: self._pair_failed(problem),
                )
                return
            self.root.after(
                0,
                lambda saved=credential, mode=transport: self._pair_finished(
                    saved,
                    mode,
                ),
            )

        threading.Thread(
            target=work,
            name="djgoo-link-pair",
            daemon=True,
        ).start()

    def _pair_finished(self, credential, transport: str) -> None:
        self._pairing_busy = False
        try:
            persisted = load_recipient_credential(self.credential_path)
        except Exception as exc:
            self._set_pairing_buttons_enabled(True)
            self._pair_failed(
                RuntimeError(
                    "The Host accepted this device, but DjGoo Voice could not "
                    f"reopen its protected credential at {self.credential_path}: {exc}"
                )
            )
            return
        if persisted.device_id != credential.device_id:
            self._set_pairing_buttons_enabled(True)
            self._pair_failed(
                RuntimeError(
                    "The saved DjGoo Voice credential did not match the device "
                    "accepted by the Host. Request a new invite and try again."
                )
            )
            return

        self._set_pairing_buttons_enabled(True)
        if self._pairing_panel is not None:
            try:
                self._pairing_panel.pack_forget()
            except Exception:
                pass
        super()._pair_finished(credential, transport)
        self.refresh_status()
        self.root.after(250, self.check_connection)
        self.root.after_idle(
            lambda: fit_window_to_content(
                self.root,
                minimum_width=900,
                minimum_height=690,
            )
        )

    def _pair_failed(self, error: Exception) -> None:
        self._pairing_busy = False
        self._set_pairing_buttons_enabled(True)
        super()._pair_failed(error)

    def refresh_status(self) -> None:
        if self._pairing_busy:
            return
        super().refresh_status()

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
