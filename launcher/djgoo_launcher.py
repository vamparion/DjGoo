from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Button, Frame, Label, StringVar, Text, Tk, messagebox


APP_NAME = "DjGoo"
RELEASES_URL = "https://github.com/vamparion/DjGoo/releases"
DISCORD_APPS_URL = "https://discord.com/developers/applications"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = int(os.environ.get("DJGOO_CONTROL_PORT", "47631"))
START_STATUS_GRACE_SECONDS = 180.0


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def runtime_python(self) -> Path:
        candidates = (
            self.root / "runtime" / "python" / "python.exe",
            self.root / ".venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        )
        return next((path for path in candidates if path.exists()), Path(sys.executable))

    @property
    def runtime_pythonw(self) -> Path:
        candidates = (
            self.root / "runtime" / "python" / "pythonw.exe",
            self.root / ".venv" / "Scripts" / "pythonw.exe",
            self.runtime_python,
        )
        return next((path for path in candidates if path.exists()), self.runtime_python)

    @property
    def stack_script(self) -> Path:
        return self.root / "tools" / "djgoo_stack.py"

    @property
    def setup_script(self) -> Path:
        return self.root / "tools" / "portable_red_setup.py"

    @property
    def state_file(self) -> Path:
        return self.root / "data" / "djgoo-supervisor-state.json"

    @property
    def redbot_pid_file(self) -> Path:
        return self.root / "data" / "pids" / "redbot.json"

    @property
    def redbot_log(self) -> Path:
        return self.root / "data" / "discordbot" / "core" / "logs" / "latest.log"

    @property
    def component_logs(self) -> Path:
        return self.root / "logs" / "components"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def marker(self) -> Path:
        return self.root / "data" / "portable-setup.json"


class DjGooLauncher:
    def __init__(self, root: Tk, layout: Layout) -> None:
        self.root = root
        self.layout = layout
        self.status_text = StringVar(value="Checking DjGoo…")
        self._requested_desired: bool | None = None
        self._requested_at = 0.0
        self._build()
        self.refresh_status()
        self.root.after(2500, self._poll)

    def _build(self) -> None:
        self.root.title("DjGoo")
        self.root.geometry("760x520")
        self.root.minsize(680, 460)

        header = Frame(self.root, padx=18, pady=16)
        header.pack(fill=X)
        Label(header, text="DjGoo", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        Label(
            header,
            text="Portable game-first Discord music and voice control",
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        status_frame = Frame(self.root, padx=18, pady=6)
        status_frame.pack(fill=X)
        Label(status_frame, text="Status:", font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        Label(status_frame, textvariable=self.status_text, font=("Segoe UI", 10)).pack(side=LEFT, padx=(8, 0))
        Button(status_frame, text="Refresh", command=self.refresh_status).pack(side=RIGHT)

        controls = Frame(self.root, padx=18, pady=8)
        controls.pack(fill=X)
        for label, action in (
            ("Start", "start"),
            ("Stop", "stop"),
            ("Restart", "reset"),
        ):
            Button(controls, text=label, width=12, command=lambda a=action: self.stack_action(a)).pack(
                side=LEFT, padx=(0, 8)
            )
        Button(controls, text="First-run setup", width=16, command=self.run_setup).pack(side=LEFT, padx=(12, 8))
        Button(controls, text="Bot console / log", width=16, command=self.run_bot_console).pack(side=LEFT)

        tools = Frame(self.root, padx=18, pady=4)
        tools.pack(fill=X)
        Button(tools, text="Open logs", command=lambda: self.open_path(self.layout.logs)).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Open settings", command=lambda: self.open_path(self.layout.config)).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Discord developer portal", command=lambda: webbrowser.open(DISCORD_APPS_URL)).pack(
            side=LEFT, padx=(0, 8)
        )
        Button(tools, text="Check releases", command=lambda: webbrowser.open(RELEASES_URL)).pack(side=LEFT)

        Label(
            self.root,
            text="Activity",
            font=("Segoe UI", 11, "bold"),
            padx=18,
            pady=8,
        ).pack(anchor="w")
        self.activity = Text(self.root, height=14, wrap="word", font=("Consolas", 9))
        self.activity.pack(fill=BOTH, expand=True, padx=18, pady=(0, 18))
        self.log("Launcher ready.")
        if not self.layout.marker.exists():
            self.log("First run detected. Use First-run setup before starting DjGoo.")

    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.activity.insert(END, f"[{stamp}] {text}\n")
        self.activity.see(END)

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DJGOO_HOME"] = str(self.layout.root)
        env["REDBOT_CONFIG_DIR"] = str(
            self.layout.root / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"
        )
        return env

    def _validate_runtime(self) -> bool:
        required = (self.layout.runtime_python, self.layout.stack_script)
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            messagebox.showerror(
                APP_NAME,
                "This package is incomplete. Missing:\n\n" + "\n".join(missing),
            )
            self.log("Package validation failed: " + ", ".join(missing))
            return False
        return True

    def _state(self) -> dict[str, object]:
        return read_json(self.layout.state_file) or {}

    def _redbot_process_active(self, state: dict[str, object] | None = None) -> bool:
        state = state or self._state()
        components = state.get("components")
        if isinstance(components, dict):
            redbot = components.get("redbot")
            if isinstance(redbot, dict):
                try:
                    pid = int(redbot.get("pid") or 0)
                except (TypeError, ValueError):
                    pid = 0
                if redbot.get("running") is True or process_exists(pid):
                    return True

        record = read_json(self.layout.redbot_pid_file)
        if record:
            try:
                return process_exists(int(record.get("pid") or 0))
            except (TypeError, ValueError):
                return False
        return False

    def _redbot_or_stack_active(self) -> bool:
        if (
            self._requested_desired is True
            and time.monotonic() - self._requested_at < START_STATUS_GRACE_SECONDS
        ):
            return True
        state = self._state()
        return bool(state.get("desired_running")) or self._redbot_process_active(state)

    def stack_action(self, action: str) -> None:
        if not self._validate_runtime():
            return
        command = [str(self.layout.runtime_pythonw), str(self.layout.stack_script), action]
        try:
            subprocess.Popen(
                command,
                cwd=self.layout.root,
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._requested_desired = action in {"start", "reset"}
            self._requested_at = time.monotonic()
            self.log(f"Requested {action}.")
            self.root.after(250, self.refresh_status)
            self.root.after(1200, self.refresh_status)
        except OSError as exc:
            self.log(f"Could not request {action}: {exc}")
            messagebox.showerror(APP_NAME, str(exc))

    def run_setup(self) -> None:
        if self._redbot_or_stack_active():
            self.log("First-run setup blocked because DjGoo is starting or running.")
            messagebox.showwarning(
                APP_NAME,
                "Stop DjGoo before running First-run setup. Editing the Redbot instance while it is active can damage its configuration.",
            )
            return
        if not self.layout.setup_script.exists():
            messagebox.showerror(APP_NAME, f"Setup helper is missing: {self.layout.setup_script}")
            return
        command = [str(self.layout.runtime_python), str(self.layout.setup_script), "--project-root", str(self.layout.root)]
        self.log("Opening guided Red/Discord setup console.")
        subprocess.Popen(
            command,
            cwd=self.layout.root,
            env=self._environment(),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )

    def run_bot_console(self) -> None:
        if not self._validate_runtime():
            return
        if self._redbot_or_stack_active():
            self.log("A duplicate Redbot console was blocked. Opening the active bot log instead.")
            messagebox.showwarning(
                APP_NAME,
                "DjGoo is already starting or running. Starting a second Redbot against the same data folder would cause a file-lock crash.\n\nThe active bot log will be opened instead.",
            )
            self.open_redbot_log()
            return
        command = [str(self.layout.runtime_python), str(self.layout.root / "tools" / "start_redbot_selector.py")]
        self.log("Opening Redbot console for first-start token prompts and direct diagnostics.")
        subprocess.Popen(
            command,
            cwd=self.layout.root,
            env=self._environment(),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )

    def open_redbot_log(self) -> None:
        if self.layout.redbot_log.exists():
            try:
                self.open_path(self.layout.redbot_log)
                return
            except OSError as exc:
                self.log(f"Could not open the active Redbot log directly: {exc}")
        self.layout.component_logs.mkdir(parents=True, exist_ok=True)
        self.open_path(self.layout.component_logs)

    def refresh_status(self) -> None:
        data = self._state()
        if not data:
            if self._requested_desired and time.monotonic() - self._requested_at < START_STATUS_GRACE_SECONDS:
                self.status_text.set("Starting — request accepted")
            else:
                self.status_text.set("Stopped or not configured")
            return

        desired = bool(data.get("desired_running"))
        if self._requested_desired is not None:
            age = time.monotonic() - self._requested_at
            if desired == self._requested_desired:
                self._requested_desired = None
            elif age < START_STATUS_GRACE_SECONDS:
                desired = self._requested_desired
            else:
                self._requested_desired = None

        components = data.get("components") if isinstance(data.get("components"), dict) else {}
        ready = [
            name
            for name, state in components.items()
            if isinstance(state, dict) and state.get("ready")
        ]
        running = [
            name
            for name, state in components.items()
            if isinstance(state, dict) and state.get("running")
        ]
        total = len(components)
        error = str(data.get("last_error") or "").strip()
        if error:
            self.status_text.set(f"Needs attention — {error}")
        elif desired and total and len(ready) == total:
            self.status_text.set(f"Running — {', '.join(sorted(ready))}")
        elif desired:
            self.status_text.set(f"Starting — {len(ready)}/{total or 3} components ready")
        elif running:
            self.status_text.set(f"Stopping — {', '.join(sorted(running))}")
        else:
            self.status_text.set("Stopped")

    def _poll(self) -> None:
        self.refresh_status()
        self.root.after(2500, self._poll)

    @staticmethod
    def open_path(path: Path) -> None:
        if path.exists():
            target = path
        elif path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            target = path.parent
        else:
            path.mkdir(parents=True, exist_ok=True)
            target = path
        os.startfile(target) if os.name == "nt" else webbrowser.open(target.as_uri())


def main() -> int:
    layout = Layout(application_root())
    layout.logs.mkdir(parents=True, exist_ok=True)
    layout.config.mkdir(parents=True, exist_ok=True)
    root = Tk()
    DjGooLauncher(root, layout)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
