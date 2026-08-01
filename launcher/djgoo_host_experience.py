from __future__ import annotations

import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Button, Frame, Label, Text, Tk, messagebox


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from launcher.djgoo_launcher import APP_NAME, DjGooLauncher, Layout, application_root
from tools.update_client import read_installed_version
from voice.command_catalog import command_tip


BG = "#11151b"
PANEL = "#191f29"
PANEL_ALT = "#222a37"
TEXT = "#f2f5fa"
MUTED = "#9ba7b8"
ACCENT = "#718cff"
GOOD = "#69d39d"
DANGER = "#e9707e"


class DjGooControlCenter(DjGooLauncher):
    def _button(self, parent, text: str, command, *, accent: bool = False, danger: bool = False, width: int | None = None):
        return Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=DANGER if danger else ACCENT if accent else PANEL_ALT,
            fg=TEXT,
            activebackground="#8da2ff" if accent else "#303a4c",
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )

    def _build(self) -> None:
        version = read_installed_version(self.layout.root).text
        self.root.title("DjGoo Control Center")
        self.root.geometry("860x620")
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        self.tip_index = 0

        header = Frame(self.root, bg=BG, padx=22, pady=18)
        header.pack(fill=X)
        Label(header, text="DJGOO", font=("Segoe UI", 24, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        Label(
            header,
            text=f"Game-first Discord DJ • {version}",
            font=("Segoe UI", 10),
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w")

        status_frame = Frame(self.root, bg=PANEL, padx=18, pady=14)
        status_frame.pack(fill=X, padx=20, pady=(0, 10))
        Label(status_frame, textvariable=self.status_text, font=("Segoe UI", 13, "bold"), bg=PANEL, fg=GOOD).pack(side=LEFT)
        self._button(status_frame, "Refresh", self.refresh_status).pack(side=RIGHT)

        controls = Frame(self.root, bg=PANEL, padx=18, pady=14)
        controls.pack(fill=X, padx=20, pady=(0, 10))
        Label(controls, text="Session", font=("Segoe UI", 11, "bold"), bg=PANEL, fg=TEXT).pack(anchor="w")
        row = Frame(controls, bg=PANEL)
        row.pack(fill=X, pady=(9, 0))
        self._button(row, "Start", partial(self.stack_action, "start"), accent=True, width=12).pack(side=LEFT, padx=(0, 7))
        self._button(row, "Stop", partial(self.stack_action, "stop"), danger=True, width=12).pack(side=LEFT, padx=(0, 7))
        self._button(row, "Recover", partial(self.stack_action, "reset"), width=12).pack(side=LEFT, padx=(0, 16))
        self._button(row, "Mini player", self.open_mini_player).pack(side=LEFT, padx=(0, 7))
        self._button(row, "Connect Discord", self.run_setup).pack(side=LEFT, padx=(0, 7))
        self._button(row, "Music Core diagnostics", self.run_bot_console).pack(side=LEFT)

        tools = Frame(self.root, bg=PANEL, padx=18, pady=14)
        tools.pack(fill=X, padx=20, pady=(0, 10))
        Label(tools, text="Manage", font=("Segoe UI", 11, "bold"), bg=PANEL, fg=TEXT).pack(anchor="w")
        tool_row = Frame(tools, bg=PANEL)
        tool_row.pack(fill=X, pady=(9, 0))
        self._button(tool_row, "Settings", partial(self.open_path, self.layout.config)).pack(side=LEFT, padx=(0, 7))
        self._button(tool_row, "Diagnostics", partial(self.open_path, self.layout.logs)).pack(side=LEFT, padx=(0, 7))
        self._button(tool_row, "Check for updates", self.check_updates).pack(side=LEFT, padx=(0, 7))

        coach = Frame(self.root, bg="#171c25", padx=18, pady=12)
        coach.pack(fill=X, padx=20, pady=(0, 10))
        Label(coach, text="TRY SAYING", font=("Segoe UI", 8, "bold"), bg="#171c25", fg=ACCENT).pack(side=LEFT)
        self.tip_label = Label(coach, text="", font=("Segoe UI", 10), bg="#171c25", fg=MUTED)
        self.tip_label.pack(side=LEFT, padx=(12, 0))

        Label(self.root, text="Activity", font=("Segoe UI", 9, "bold"), bg=BG, fg=MUTED, padx=20).pack(anchor="w")
        self.activity = Text(
            self.root,
            height=10,
            wrap="word",
            font=("Consolas", 9),
            bg="#0d1016",
            fg="#aeb8c8",
            insertbackground=TEXT,
            relief="flat",
        )
        self.activity.pack(fill=BOTH, expand=True, padx=20, pady=(4, 18))
        self.log("Control Center ready.")
        if not self.layout.marker.exists():
            self.log("First use detected. Select Connect Discord before starting DjGoo.")
        self._rotate_tip()

    def _rotate_tip(self) -> None:
        hint = command_tip(self.tip_index)
        self.tip_index += 1
        self.tip_label.configure(text=f"“{hint.phrase}”  —  {hint.description}")
        self.root.after(8000, self._rotate_tip)

    def refresh_status(self) -> None:
        super().refresh_status()
        text = self.status_text.get()
        replacements = {
            "redbot": "Music Core",
            "lavalink": "Audio Engine",
            "voice": "Voice Control",
            "Redbot": "Music Core",
            "Lavalink": "Audio Engine",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        self.status_text.set(text)

    def open_mini_player(self) -> None:
        executable = self.layout.root / "DjGoo Mini Player.exe"
        if executable.exists():
            subprocess.Popen(
                [str(executable)],
                cwd=self.layout.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.log("Opened Mini Player.")
            return
        source = self.layout.root / "launcher" / "djgoo_overlay.py"
        if source.exists():
            subprocess.Popen(
                [str(self.layout.runtime_pythonw), str(source)],
                cwd=self.layout.root,
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.log("Opened Mini Player from source runtime.")
            return
        messagebox.showerror(APP_NAME, "The DjGoo Mini Player is missing from this package.")


def main() -> int:
    layout = Layout(application_root())
    layout.logs.mkdir(parents=True, exist_ok=True)
    layout.config.mkdir(parents=True, exist_ok=True)
    root = Tk()
    DjGooControlCenter(root, layout)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
