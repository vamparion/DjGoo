from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, Tk, messagebox, simpledialog

import launcher.djgoo_voice_launcher as voice_base
from launcher.djgoo_theme import (
    ACCENT,
    ACCENT_2,
    BG,
    DANGER,
    GOOD,
    MUTED,
    PANEL,
    PANEL_ALT,
    TEXT,
    WARN,
)


# The Host and recipient intentionally use the exact same palette.
voice_base.BG = BG
voice_base.PANEL = PANEL
voice_base.PANEL_ALT = PANEL_ALT
voice_base.TEXT = TEXT
voice_base.MUTED = MUTED
voice_base.ACCENT = ACCENT
voice_base.ACCENT_2 = ACCENT_2
voice_base.GOOD = GOOD
voice_base.WARN = WARN
voice_base.DANGER = DANGER

from launcher.djgoo_voice_experience import DjGooVoiceExperience
from tools.update_auth import clear_token, load_token, save_token
from tools.update_client import AuthenticationRequired, UpdateError, UpdateOffer, read_installed_version
from tools.voice_update_client import check_for_voice_update, download_voice_update
from voice.input_binding import capture_next_button, normalize_button_name


APP_TITLE = "DjGoo Voice"


class DjGooVoiceControlCenter(DjGooVoiceExperience):
    def __init__(self, root: Tk, project_root: Path) -> None:
        self._binding_button = False
        self._update_busy = False
        self.update_auth_path = project_root / "config" / "update-auth.json"
        self.update_result_path = project_root / "data" / "update-result.json"
        self.update_worker_path = project_root / "tools" / "apply_voice_update.py"
        super().__init__(root, project_root)
        self._report_update_result()

    def _field(self, parent: Frame, row: int, label: str, variable) -> None:
        if label != "Push-to-talk":
            super()._field(parent, row, label, variable)
            return
        Label(parent, text=label, width=16, anchor="w", bg=PANEL, fg=MUTED).grid(
            row=row,
            column=0,
            sticky="w",
            pady=4,
        )
        Label(
            parent,
            textvariable=variable,
            anchor="w",
            bg="#0f131a",
            fg=TEXT,
            padx=8,
            pady=6,
        ).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        self._button(parent, "Bind a button", self.bind_button, accent=True).grid(
            row=row,
            column=3,
            sticky="e",
            padx=(8, 0),
            pady=4,
        )

    def _build(self) -> None:
        super()._build()
        version = read_installed_version(self.project_root).text
        manage = Frame(self.root, bg=PANEL, padx=18, pady=12)
        manage.pack(fill=X, padx=20, pady=(0, 10), before=self.activity)
        Label(
            manage,
            text=f"Manage • {version}",
            font=("Segoe UI", 10, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(side=LEFT)
        self._button(manage, "Check for updates", self.check_updates).pack(side=LEFT, padx=(14, 0))
        Label(
            manage,
            text="Same theme and verified updater as the DjGoo Host.",
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT, padx=(12, 0))

    def bind_button(self) -> None:
        if self._binding_button:
            return
        self._binding_button = True
        self.log("Button binding armed. Release the mouse, then press the desired keyboard or mouse button.")
        threading.Thread(target=self._capture_button_worker, name="djgoo-voice-bind", daemon=True).start()

    def _capture_button_worker(self) -> None:
        try:
            captured = capture_next_button()
        except Exception as exc:
            self.root.after(0, lambda: self._finish_button_binding(None, str(exc)))
            return
        self.root.after(0, lambda: self._finish_button_binding(captured, None))

    def _finish_button_binding(self, captured: str | None, error: str | None) -> None:
        self._binding_button = False
        if not captured:
            self.log(f"Button binding cancelled: {error or 'no input detected'}")
            messagebox.showerror(APP_TITLE, error or "No button was detected.", parent=self.root)
            return
        normalized = normalize_button_name(captured)
        self.hotkey.set(normalized)
        self.save_settings()
        self.log(f"Push-to-talk button saved as {normalized}.")
        if self._running_pid() is not None:
            messagebox.showinfo(
                APP_TITLE,
                f"Push-to-talk is now {normalized}. Stop and start listening to apply it.",
                parent=self.root,
            )

    def save_settings(self) -> None:
        self.hotkey.set(normalize_button_name(self.hotkey.get() or "F12"))
        super().save_settings()

    def start(self) -> None:
        if not self.credential_path.exists():
            messagebox.showerror(APP_TITLE, "Connect this device before starting voice control.")
            return
        if self._running_pid() is not None:
            self.log("Voice control is already listening.")
            return
        self.save_settings()
        logs = self.project_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stdout = (logs / "voice-remote.out.log").open("ab")
        stderr = (logs / "voice-remote.err.log").open("ab")
        process = subprocess.Popen(
            [
                str(self.runtime_pythonw),
                "-m",
                "voice.djgoo_voice_remote_bound",
                "--project-root",
                str(self.project_root),
                "run",
            ],
            cwd=self.project_root,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(process.pid), encoding="ascii")
        self.log("Voice control started.")
        self.refresh_status()

    def check_updates(self) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        self.log("Checking GitHub for a verified DjGoo Voice update…")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self, token: str | None = None, prompted: bool = False) -> None:
        resolved = token if token is not None else load_token(self.update_auth_path)
        try:
            offer = check_for_voice_update(self.project_root, resolved)
        except AuthenticationRequired:
            if resolved:
                clear_token(self.update_auth_path)
            self.root.after(0, lambda: self._request_update_token(prompted))
            return
        except (UpdateError, Exception) as exc:
            self.root.after(0, lambda: self._finish_update_error(str(exc)))
            return
        if offer is None:
            self.root.after(0, self._finish_no_update)
        else:
            self.root.after(0, lambda: self._confirm_update(offer, resolved))

    def _request_update_token(self, already_prompted: bool) -> None:
        if already_prompted:
            self._finish_update_error(
                "GitHub rejected the token. Use a fine-grained token with read-only Contents access to DjGoo."
            )
            return
        token = simpledialog.askstring(
            "Private DjGoo updates",
            "Enter a fine-grained GitHub token with read-only Contents access to DjGoo.\n\n"
            "It is encrypted for this Windows account and is not written to logs.",
            show="*",
            parent=self.root,
        )
        if not token:
            self._update_busy = False
            self.log("Update check cancelled.")
            return
        try:
            save_token(self.update_auth_path, token)
        except Exception as exc:
            self._finish_update_error(f"Could not securely save the update token: {exc}")
            return
        threading.Thread(target=self._check_update_worker, args=(token, True), daemon=True).start()

    def _finish_no_update(self) -> None:
        self._update_busy = False
        self.log("DjGoo Voice is already up to date.")
        messagebox.showinfo(APP_TITLE, "DjGoo Voice is already up to date.", parent=self.root)

    def _finish_update_error(self, error: str) -> None:
        self._update_busy = False
        self.log("Update failed: " + error)
        messagebox.showerror(APP_TITLE, error, parent=self.root)

    def _confirm_update(self, offer: UpdateOffer, token: str | None) -> None:
        installed = read_installed_version(self.project_root).text
        if not messagebox.askyesno(
            APP_TITLE,
            f"DjGoo Voice {offer.version.text} is available.\n\nInstalled: {installed}\nAvailable: {offer.version.text}\n\nInstall it now?",
            parent=self.root,
        ):
            self._update_busy = False
            return
        self.log(f"Downloading DjGoo Voice {offer.version.text}…")
        threading.Thread(target=self._download_update_worker, args=(offer, token), daemon=True).start()

    def _download_update_worker(self, offer: UpdateOffer, token: str | None) -> None:
        progress_bucket = -10

        def progress(downloaded: int, total: int) -> None:
            nonlocal progress_bucket
            if total <= 0:
                return
            bucket = min(100, int(downloaded * 100 / total)) // 10 * 10
            if bucket > progress_bucket:
                progress_bucket = bucket
                self.root.after(0, lambda b=bucket: self.log(f"Update download: {b}%"))

        try:
            bundle, manifest, _ = download_voice_update(self.project_root, offer, token, progress)
        except Exception as exc:
            self.root.after(0, lambda: self._finish_update_error(str(exc)))
            return
        self.root.after(0, lambda: self._launch_update_worker(bundle, manifest, offer))

    def _launch_update_worker(self, bundle: Path, manifest: Path, offer: UpdateOffer) -> None:
        if not self.update_worker_path.exists():
            self._finish_update_error(f"Update worker is missing: {self.update_worker_path}")
            return
        if self._running_pid() is not None:
            self.stop()
        try:
            subprocess.Popen(
                [
                    str(self.runtime_pythonw),
                    str(self.update_worker_path),
                    "--root",
                    str(self.project_root),
                    "--bundle",
                    str(bundle),
                    "--manifest",
                    str(manifest),
                    "--parent-pid",
                    str(os.getpid()),
                ],
                cwd=self.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        except OSError as exc:
            self._finish_update_error(f"Could not start the update worker: {exc}")
            return
        self.log(f"Installing DjGoo Voice {offer.version.text}; the controller will restart.")
        self.root.after(300, self.root.destroy)

    def _report_update_result(self) -> None:
        if not self.update_result_path.exists():
            return
        try:
            payload = json.loads(self.update_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.update_result_path.unlink(missing_ok=True)
        if bool(payload.get("success")):
            self.log(f"Update completed successfully: DjGoo Voice {payload.get('version') or 'new version'}.")
            return
        error = str(payload.get("error") or "Unknown update error")
        self.log("Previous update failed: " + error)
        messagebox.showerror(
            APP_TITLE,
            "The previous DjGoo Voice update failed and was rolled back.\n\n" + error,
            parent=self.root,
        )


def main() -> int:
    root = Tk()
    DjGooVoiceControlCenter(root, voice_base.application_root())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
