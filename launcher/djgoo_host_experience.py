from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from pathlib import Path
from tkinter import (
    BOTH,
    LEFT,
    RIGHT,
    X,
    Button,
    Frame,
    Label,
    Text,
    Tk,
    messagebox,
    simpledialog,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from launcher.djgoo_launcher import (
    APP_NAME,
    DISCORD_APPS_URL,
    DjGooLauncher,
    Layout,
    application_root,
)
from tools.configure_music_core import (
    PREFIX_ENV,
    TOKEN_ENV,
    validate_prefix,
    validate_token,
)
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
        Label(
            header,
            text="DJGOO",
            font=("Segoe UI", 24, "bold"),
            bg=BG,
            fg=TEXT,
        ).pack(anchor="w")
        Label(
            header,
            text=f"Game-first Discord DJ • {version}",
            font=("Segoe UI", 10),
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w")

        status_frame = Frame(self.root, bg=PANEL, padx=18, pady=14)
        status_frame.pack(fill=X, padx=20, pady=(0, 10))
        Label(
            status_frame,
            textvariable=self.status_text,
            font=("Segoe UI", 13, "bold"),
            bg=PANEL,
            fg=GOOD,
        ).pack(side=LEFT)
        self._button(
            status_frame,
            "Refresh",
            self.refresh_status,
        ).pack(side=RIGHT)

        controls = Frame(self.root, bg=PANEL, padx=18, pady=14)
        controls.pack(fill=X, padx=20, pady=(0, 10))
        Label(
            controls,
            text="Session",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(anchor="w")
        row = Frame(controls, bg=PANEL)
        row.pack(fill=X, pady=(9, 0))
        self._button(
            row,
            "Start",
            partial(self.stack_action, "start"),
            accent=True,
            width=12,
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            row,
            "Stop",
            partial(self.stack_action, "stop"),
            danger=True,
            width=12,
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            row,
            "Recover",
            partial(self.stack_action, "reset"),
            width=12,
        ).pack(side=LEFT, padx=(0, 16))
        self._button(
            row,
            "Open DjGoo",
            self.open_mini_player,
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            row,
            "Connect Discord",
            self.run_setup,
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            row,
            "Music Core diagnostics",
            self.run_bot_console,
        ).pack(side=LEFT)

        tools = Frame(self.root, bg=PANEL, padx=18, pady=14)
        tools.pack(fill=X, padx=20, pady=(0, 10))
        Label(
            tools,
            text="Manage",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL,
            fg=TEXT,
        ).pack(anchor="w")
        tool_row = Frame(tools, bg=PANEL)
        tool_row.pack(fill=X, pady=(9, 0))
        self._button(
            tool_row,
            "Settings",
            partial(self.open_path, self.layout.config),
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            tool_row,
            "Diagnostics",
            partial(self.open_path, self.layout.logs),
        ).pack(side=LEFT, padx=(0, 7))
        self._button(
            tool_row,
            "Check for updates",
            self.check_updates,
        ).pack(side=LEFT, padx=(0, 7))

        coach = Frame(
            self.root,
            bg="#171c25",
            padx=18,
            pady=12,
        )
        coach.pack(fill=X, padx=20, pady=(0, 10))
        Label(
            coach,
            text="TRY SAYING",
            font=("Segoe UI", 8, "bold"),
            bg="#171c25",
            fg=ACCENT,
        ).pack(side=LEFT)
        self.tip_label = Label(
            coach,
            text="",
            font=("Segoe UI", 10),
            bg="#171c25",
            fg=MUTED,
        )
        self.tip_label.pack(side=LEFT, padx=(12, 0))

        Label(
            self.root,
            text="Activity",
            font=("Segoe UI", 9, "bold"),
            bg=BG,
            fg=MUTED,
            padx=20,
        ).pack(anchor="w")
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
        self.activity.pack(
            fill=BOTH,
            expand=True,
            padx=20,
            pady=(4, 18),
        )
        self.log("Control Center ready.")
        if not self.layout.marker.exists():
            self.log(
                "First use detected. Select Connect Discord before starting DjGoo."
            )
        self._rotate_tip()

    def _rotate_tip(self) -> None:
        hint = command_tip(self.tip_index)
        self.tip_index += 1
        self.tip_label.configure(
            text=f"“{hint.phrase}”  —  {hint.description}"
        )
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

    def run_setup(self) -> None:
        if self._redbot_or_stack_active():
            messagebox.showwarning(
                APP_NAME,
                "Stop DjGoo before changing its Discord connection.",
            )
            return
        helper = self.layout.root / "tools" / "configure_music_core.py"
        if not helper.exists():
            messagebox.showerror(
                APP_NAME,
                f"The Discord connection helper is missing: {helper}",
            )
            return

        open_portal = messagebox.askyesno(
            "Connect DjGoo to Discord",
            "DjGoo needs a Discord bot token from your own bot application.\n\n"
            "Open the Discord Developer Portal now?",
            parent=self.root,
        )
        if open_portal:
            webbrowser.open(DISCORD_APPS_URL)

        token = simpledialog.askstring(
            "Connect DjGoo to Discord",
            "Paste the bot token from the Discord Developer Portal.\n\n"
            "DjGoo passes it to the Music Core through a temporary child environment; "
            "it is not placed in the process command line or launcher logs.",
            show="*",
            parent=self.root,
        )
        if token is None:
            return
        prefix = simpledialog.askstring(
            "DjGoo command prefix",
            "Choose the classic text-command prefix. Most users should keep `!`.\n\n"
            "Voice commands, DjGoo chat commands, buttons, and slash commands do not depend on this prefix.",
            initialvalue="!",
            parent=self.root,
        )
        if prefix is None:
            return
        try:
            validated_token = validate_token(token)
            validated_prefix = validate_prefix(prefix)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return

        self.log("Configuring DjGoo's Discord connection…")
        self.status_text.set("Connecting Discord — configuring Music Core")
        threading.Thread(
            target=self._configure_discord_worker,
            args=(helper, validated_token, validated_prefix),
            name="djgoo-discord-setup",
            daemon=True,
        ).start()

    def _configure_discord_worker(
        self,
        helper: Path,
        token: str,
        prefix: str,
    ) -> None:
        environment = self._environment()
        environment[TOKEN_ENV] = token
        environment[PREFIX_ENV] = prefix
        try:
            result = subprocess.run(
                [str(self.layout.runtime_python), str(helper)],
                cwd=self.layout.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._post(self._finish_discord_setup, False, str(exc))
            return
        finally:
            environment.pop(TOKEN_ENV, None)
            environment.pop(PREFIX_ENV, None)
            token = ""
        output = (result.stdout or "").strip()
        self._post(
            self._finish_discord_setup,
            result.returncode == 0,
            output,
        )

    def _finish_discord_setup(
        self,
        success: bool,
        output: str,
    ) -> None:
        if success:
            self.log("Discord connection configured. Select Start.")
            self.refresh_status()
            messagebox.showinfo(
                APP_NAME,
                "DjGoo is connected to your Discord bot configuration.\n\n"
                "Invite the bot to your server if needed, join a voice channel, then select Start.",
                parent=self.root,
            )
            return
        sanitized = output.replace("Red-DiscordBot", "Music Core").replace(
            "Red",
            "Music Core",
        )
        self.log(
            "Discord connection failed: "
            + (sanitized[-800:] if sanitized else "unknown error")
        )
        self.status_text.set("Needs attention — Discord connection failed")
        messagebox.showerror(
            APP_NAME,
            "DjGoo could not save the Discord connection.\n\n"
            + (sanitized[-1200:] if sanitized else "No diagnostic output was returned."),
            parent=self.root,
        )

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
        source = self.layout.root / "launcher" / "djgoo_web_shell.py"
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
        messagebox.showerror(
            APP_NAME,
            "The DjGoo Mini Player is missing from this package.",
        )

    def open_radio_library(self) -> None:
        webbrowser.open("https://127.0.0.1:8765/")


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
