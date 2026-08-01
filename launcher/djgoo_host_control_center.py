from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from tkinter import LEFT, X, Frame, Label, StringVar, Tk, messagebox

from launcher.djgoo_host_experience import (
    BG,
    MUTED,
    PANEL,
    TEXT,
    DjGooControlCenter,
    Layout,
    application_root,
)
from launcher.djgoo_launcher import START_STATUS_GRACE_SECONDS
from tools.legacy_music_core import migrate_existing_music_core
from voice.input_binding import capture_next_button, normalize_button_name


class DjGooHostControlCenter(DjGooControlCenter):
    def __init__(self, root: Tk, layout: Layout) -> None:
        self._legacy_music_core_migrated = migrate_existing_music_core(layout.root)
        self.hotkey = StringVar(root, value=self._load_host_hotkey(layout.root))
        self._binding_button = False
        super().__init__(root, layout)
        if self._legacy_music_core_migrated:
            self.log("Existing Discord configuration restored from the previous DjGoo installation.")
            self.status_text.set("Stopped — existing Discord connection ready")

    @staticmethod
    def _secrets_path(root: Path) -> Path:
        return root / "config" / "secrets.json"

    @classmethod
    def _load_host_hotkey(cls, root: Path) -> str:
        try:
            payload = json.loads(cls._secrets_path(root).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "F12"
        voice = payload.get("voice") if isinstance(payload, dict) else None
        if not isinstance(voice, dict):
            return "F12"
        return normalize_button_name(str(voice.get("hotkey") or "F12"))

    def _build(self) -> None:
        super()._build()
        voice_panel = Frame(self.root, bg=PANEL, padx=18, pady=12)
        voice_panel.pack(fill=X, padx=20, pady=(0, 10), before=self.activity)
        Label(
            voice_panel,
            text="Voice control",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(anchor="w")
        row = Frame(voice_panel, bg=PANEL)
        row.pack(fill=X, pady=(8, 0))
        Label(
            row,
            text="Push-to-talk button",
            width=20,
            anchor="w",
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT)
        Label(
            row,
            textvariable=self.hotkey,
            width=18,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(side=LEFT, padx=(0, 8))
        self._button(row, "Bind a button", self.bind_button, accent=True).pack(side=LEFT)
        Label(
            row,
            text="Press any keyboard or mouse button after selecting Bind.",
            bg=PANEL,
            fg=MUTED,
        ).pack(side=LEFT, padx=(12, 0))

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

    def bind_button(self) -> None:
        if self._binding_button:
            return
        self._binding_button = True
        self.log("Button binding armed. Release the mouse, then press the desired keyboard or mouse button.")
        threading.Thread(target=self._capture_button_worker, name="djgoo-host-bind", daemon=True).start()

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
            messagebox.showerror("DjGoo", error or "No button was detected.", parent=self.root)
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
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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
