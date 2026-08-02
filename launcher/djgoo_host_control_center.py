from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, StringVar, Tk, messagebox

import launcher.djgoo_host_experience as host_base
import launcher.djgoo_launcher as launcher_base
from launcher.djgoo_launcher import START_STATUS_GRACE_SECONDS
from launcher.djgoo_theme import (
    ACCENT,
    ACTIVE_ACCENT,
    ACTIVE_DANGER,
    ACTIVE_PANEL,
    BG,
    DANGER,
    GOOD,
    MUTED,
    PANEL,
    PANEL_ALT,
    TEXT,
)
from launcher.frozen_shutdown import install_frozen_shutdown
from launcher.window_layout import fit_window_to_content
from tools.update_client_guard import check_for_update as guarded_check_for_update


# The Host and recipient intentionally use one shared palette module.
host_base.BG = BG
host_base.PANEL = PANEL
host_base.PANEL_ALT = PANEL_ALT
host_base.TEXT = TEXT
host_base.MUTED = MUTED
host_base.ACCENT = ACCENT
host_base.GOOD = GOOD
host_base.DANGER = DANGER
# Replace the base launcher's silent incomplete-release behavior.
launcher_base.check_for_update = guarded_check_for_update

DjGooControlCenter = host_base.DjGooControlCenter
Layout = host_base.Layout
application_root = host_base.application_root

from tools.legacy_music_core import migrate_existing_music_core
from tools.windows_firewall import ensure_gateway_firewall
from voice.input_binding import capture_next_button, normalize_button_name


class DjGooHostControlCenter(DjGooControlCenter):
    def __init__(self, root: Tk, layout: Layout) -> None:
        self._legacy_music_core_migrated = migrate_existing_music_core(layout.root)
        self.hotkey = StringVar(root, value=self._load_host_hotkey(layout.root))
        self._binding_button = False
        self._firewall_busy = False
        super().__init__(root, layout)
        install_frozen_shutdown(self.root)
        if self._legacy_music_core_migrated:
            self.log(
                "Existing Discord configuration restored from the previous DjGoo installation."
            )
            self.status_text.set("Stopped — existing Discord connection ready")
        self.root.after(400, self.ensure_local_link)

    def _button(
        self,
        parent,
        text: str,
        command,
        *,
        accent: bool = False,
        danger: bool = False,
        width: int | None = None,
    ):
        button = super()._button(
            parent,
            text,
            command,
            accent=accent,
            danger=danger,
            width=width,
        )
        button.configure(
            bg=DANGER if danger else ACCENT if accent else PANEL_ALT,
            activebackground=(
                ACTIVE_DANGER if danger else ACTIVE_ACCENT if accent else ACTIVE_PANEL
            ),
            fg=TEXT,
            activeforeground=TEXT,
        )
        return button

    @staticmethod
    def _secrets_path(root: Path) -> Path:
        return root / "config" / "secrets.json"

    @classmethod
    def _load_host_hotkey(cls, root: Path) -> str:
        try:
            payload = json.loads(
                cls._secrets_path(root).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return "F12"
        voice = payload.get("voice") if isinstance(payload, dict) else None
        if not isinstance(voice, dict):
            return "F12"
        return normalize_button_name(str(voice.get("hotkey") or "F12"))

    def _build(self) -> None:
        super()._build()
        self.activity.configure(height=6)
        voice_panel = Frame(self.root, bg=PANEL, padx=16, pady=10)
        voice_panel.pack(fill=X, padx=20, pady=(0, 10), before=self.activity)
        Label(
            voice_panel,
            text="Voice control",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(anchor="w")
        row = Frame(voice_panel, bg=PANEL)
        row.pack(fill=X, pady=(7, 0))
        Label(
            row,
            text="Push-to-talk",
            width=14,
            anchor="w",
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT)
        Label(
            row,
            textvariable=self.hotkey,
            width=10,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(side=LEFT, padx=(0, 8))
        self._button(
            row,
            "Bind a button",
            self.bind_button,
            accent=True,
        ).pack(side=LEFT)
        self._button(
            row,
            "Repair local link",
            self.ensure_local_link,
        ).pack(side=LEFT, padx=(8, 0))
        Label(
            row,
            text="Keyboard and mouse buttons are detected automatically.",
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT, padx=(12, 0))
        self.root.after_idle(
            lambda: fit_window_to_content(
                self.root,
                minimum_width=820,
                minimum_height=610,
            )
        )

    def _redbot_or_stack_active(self) -> bool:
        """Block configuration only for active Music Core work, not its idle supervisor."""

        state = self._state()
        age = time.monotonic() - self._requested_at
        if self._requested_desired is True and age < START_STATUS_GRACE_SECONDS:
            return True
        if self._redbot_process_active(state):
            return True
        if self._requested_desired is False and age < START_STATUS_GRACE_SECONDS:
            return False
        return bool(state.get("desired_running"))

    def ensure_local_link(self) -> None:
        if self._firewall_busy:
            return
        self._firewall_busy = True
        self.log("Checking the Windows local-link firewall rule…")
        threading.Thread(
            target=self._firewall_worker,
            name="djgoo-firewall-repair",
            daemon=True,
        ).start()

    def _firewall_worker(self) -> None:
        try:
            success, detail = ensure_gateway_firewall(self.layout.root, port=47632)
        except Exception as exc:
            success, detail = False, f"{type(exc).__name__}: {exc}"
        self.root.after(
            0,
            lambda: self._finish_firewall_check(success, detail),
        )

    def _finish_firewall_check(self, success: bool, detail: str) -> None:
        self._firewall_busy = False
        if success:
            if detail == "created":
                self.log("Local DjGoo Voice connections are allowed through Windows Firewall.")
            else:
                self.log("Local DjGoo Voice firewall rule is ready.")
            return
        self.log("Local link needs attention: " + detail)
        messagebox.showwarning(
            "DjGoo Link",
            detail,
            parent=self.root,
        )

    def open_mini_player(self) -> None:
        executable = self.layout.root / "DjGoo Mini Player.exe"
        if not executable.exists():
            super().open_mini_player()
            return
        subprocess.Popen(
            [str(executable)],
            cwd=self.layout.root,
            env=self._environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.log("Opened Mini Player.")

    def bind_button(self) -> None:
        if self._binding_button:
            return
        self._binding_button = True
        self.log(
            "Button binding armed. Release the mouse, then press the desired keyboard or mouse button."
        )
        threading.Thread(
            target=self._capture_button_worker,
            name="djgoo-host-bind",
            daemon=True,
        ).start()

    def _capture_button_worker(self) -> None:
        try:
            captured = capture_next_button()
        except Exception as exc:
            error = str(exc)
            self.root.after(
                0,
                lambda message=error: self._finish_button_binding(None, message),
            )
            return
        self.root.after(
            0,
            lambda button=captured: self._finish_button_binding(button, None),
        )

    def _finish_button_binding(
        self,
        captured: str | None,
        error: str | None,
    ) -> None:
        self._binding_button = False
        if not captured:
            self.log(f"Button binding cancelled: {error or 'no input detected'}")
            messagebox.showerror(
                "DjGoo",
                error or "No button was detected.",
                parent=self.root,
            )
            return
        normalized = normalize_button_name(captured)
        self.hotkey.set(normalized)
        self._save_host_hotkey(normalized)
        self.log(f"Push-to-talk button saved as {normalized}.")
        if self._redbot_process_active():
            messagebox.showinfo(
                "DjGoo",
                f"Push-to-talk is now {normalized}. Restart DjGoo to apply it to the active listener.",
                parent=self.root,
            )

    def _save_host_hotkey(self, hotkey: str) -> None:
        path = self._secrets_path(self.layout.root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        voice = payload.get("voice")
        voice = dict(voice) if isinstance(voice, dict) else {}
        voice["push_to_talk"] = True
        voice["hotkey"] = normalize_button_name(hotkey)
        payload["voice"] = voice
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


def main() -> int:
    layout = Layout(application_root())
    layout.logs.mkdir(parents=True, exist_ok=True)
    layout.config.mkdir(parents=True, exist_ok=True)
    root = Tk()
    DjGooHostControlCenter(root, layout)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
