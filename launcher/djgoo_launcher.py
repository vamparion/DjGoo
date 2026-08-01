from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    X,
    Button,
    Frame,
    Label,
    StringVar,
    Text,
    Tk,
    messagebox,
    simpledialog,
)
from typing import Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.portable_environment import portable_environment
from tools.update_auth import clear_token, load_token, save_token
from tools.update_client import (
    AuthenticationRequired,
    UpdateError,
    UpdateOffer,
    check_for_update,
    download_update,
    read_installed_version,
)


APP_NAME = "DjGoo"
RELEASES_URL = "https://github.com/vamparion/DjGoo/releases"
DISCORD_APPS_URL = "https://discord.com/developers/applications"
START_STATUS_GRACE_SECONDS = 180.0


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


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
    def bot_console_script(self) -> Path:
        return self.root / "tools" / "start_redbot_selector.py"

    @property
    def update_worker(self) -> Path:
        return self.root / "tools" / "apply_update.py"

    @property
    def update_auth(self) -> Path:
        return self.root / "config" / "update-auth.json"

    @property
    def update_result(self) -> Path:
        return self.root / "data" / "update-result.json"

    @property
    def state_file(self) -> Path:
        return self.root / "data" / "djgoo-supervisor-state.json"

    @property
    def supervisor_pid_file(self) -> Path:
        return self.root / "data" / "pids" / "supervisor.json"

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
        self._update_busy = False
        self._requested_desired: bool | None = None
        self._requested_at = 0.0
        self._ui_queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._build()
        self._report_update_result()
        self.refresh_status()
        self.root.after(100, self._drain_ui_queue)
        self.root.after(2500, self._poll)

    def _build(self) -> None:
        version = read_installed_version(self.layout.root).text
        self.root.title("DjGoo")
        self.root.geometry("790x540")
        self.root.minsize(700, 480)

        header = Frame(self.root, padx=18, pady=16)
        header.pack(fill=X)
        Label(header, text="DjGoo", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        Label(
            header,
            text=f"Portable game-first Discord music and voice control — {version}",
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        status_frame = Frame(self.root, padx=18, pady=6)
        status_frame.pack(fill=X)
        Label(status_frame, text="Status:", font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        Label(status_frame, textvariable=self.status_text, font=("Segoe UI", 10)).pack(side=LEFT, padx=(8, 0))
        Button(status_frame, text="Refresh", command=self.refresh_status).pack(side=RIGHT)

        controls = Frame(self.root, padx=18, pady=8)
        controls.pack(fill=X)
        for label, action in (("Start", "start"), ("Stop", "stop"), ("Restart", "reset")):
            Button(controls, text=label, width=12, command=partial(self.stack_action, action)).pack(
                side=LEFT, padx=(0, 8)
            )
        Button(controls, text="First-run setup", width=16, command=self.run_setup).pack(side=LEFT, padx=(12, 8))
        Button(controls, text="Bot console / log", width=16, command=self.run_bot_console).pack(side=LEFT)

        tools = Frame(self.root, padx=18, pady=4)
        tools.pack(fill=X)
        Button(tools, text="Open logs", command=partial(self.open_path, self.layout.logs)).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Open settings", command=partial(self.open_path, self.layout.config)).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Check for updates", command=self.check_updates).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Discord portal", command=partial(webbrowser.open, DISCORD_APPS_URL)).pack(side=LEFT, padx=(0, 8))
        Button(tools, text="Release page", command=partial(webbrowser.open, RELEASES_URL)).pack(side=LEFT)

        Label(self.root, text="Activity", font=("Segoe UI", 11, "bold"), padx=18, pady=8).pack(anchor="w")
        self.activity = Text(self.root, height=14, wrap="word", font=("Consolas", 9))
        self.activity.pack(fill=BOTH, expand=True, padx=18, pady=(0, 18))
        self.log("Launcher ready.")
        if not self.layout.marker.exists():
            self.log("First run detected. Use First-run setup before starting DjGoo.")

    def _post(self, callback: Callable[..., None], *args: object) -> None:
        self._ui_queue.put(partial(callback, *args))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        try:
            self.root.after(100, self._drain_ui_queue)
        except Exception:
            pass

    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.activity.insert(END, f"[{stamp}] {text}\n")
        self.activity.see(END)

    def _thread_log(self, text: str) -> None:
        self._post(self.log, text)

    def _environment(self) -> dict[str, str]:
        return portable_environment(self.layout.root, os.environ)

    def _validate_runtime(self) -> bool:
        required = (self.layout.runtime_python, self.layout.stack_script)
        missing = [str(path) for path in required if not path.exists()]
        if not missing:
            return True
        messagebox.showerror(APP_NAME, "This package is incomplete. Missing:\n\n" + "\n".join(missing))
        self.log("Package validation failed: " + ", ".join(missing))
        return False

    def _state(self) -> dict[str, object]:
        return read_json(self.layout.state_file) or {}

    @staticmethod
    def _recorded_process_active(path: Path) -> bool:
        record = read_json(path)
        if not record:
            return False
        try:
            return process_exists(int(record.get("pid") or 0))
        except (TypeError, ValueError):
            return False

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
                if process_exists(pid):
                    return True
        return self._recorded_process_active(self.layout.redbot_pid_file)

    def _redbot_or_stack_active(self) -> bool:
        if (
            self._requested_desired is True
            and time.monotonic() - self._requested_at < START_STATUS_GRACE_SECONDS
        ):
            return True
        return self._recorded_process_active(
            self.layout.supervisor_pid_file
        ) or self._redbot_process_active()

    def stack_action(self, action: str) -> None:
        if not self._validate_runtime():
            return
        try:
            subprocess.Popen(
                [str(self.layout.runtime_pythonw), str(self.layout.stack_script), action],
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
        self.log("Opening guided Red/Discord setup console.")
        try:
            subprocess.Popen(
                [
                    str(self.layout.runtime_python),
                    str(self.layout.setup_script),
                    "--project-root",
                    str(self.layout.root),
                ],
                cwd=self.layout.root,
                env=self._environment(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            self.log(f"Could not open first-run setup: {exc}")
            messagebox.showerror(APP_NAME, str(exc))

    def run_bot_console(self) -> None:
        if not self._validate_runtime():
            return
        if not self.layout.bot_console_script.exists():
            messagebox.showerror(APP_NAME, f"Bot console helper is missing: {self.layout.bot_console_script}")
            return
        if self._redbot_or_stack_active():
            self.log("A duplicate Redbot console was blocked. Opening the active bot log instead.")
            messagebox.showwarning(
                APP_NAME,
                "DjGoo is already starting or running. Starting a second Redbot against the same data folder would cause a file-lock crash.\n\nThe active bot log will be opened instead.",
            )
            self.open_redbot_log()
            return
        self.log("Opening Redbot console. Token and prefix prompts will remain visible.")
        try:
            subprocess.Popen(
                [
                    str(self.layout.runtime_python),
                    str(self.layout.bot_console_script),
                    "--djgoo-console",
                ],
                cwd=self.layout.root,
                env=self._environment(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as exc:
            self.log(f"Could not open Redbot console: {exc}")
            messagebox.showerror(APP_NAME, str(exc))

    def open_redbot_log(self) -> None:
        if self.layout.redbot_log.exists():
            try:
                self.open_path(self.layout.redbot_log)
                return
            except OSError as exc:
                self.log(f"Could not open the active Redbot log directly: {exc}")
        self.layout.component_logs.mkdir(parents=True, exist_ok=True)
        self.open_path(self.layout.component_logs)

    def check_updates(self) -> None:
        if self._update_busy:
            self.log("An update check is already running.")
            return
        self._update_busy = True
        self.log("Checking GitHub for a verified incremental update…")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self, token: str | None = None, prompted: bool = False) -> None:
        resolved_token = token if token is not None else load_token(self.layout.update_auth)
        try:
            offer = check_for_update(self.layout.root, resolved_token)
        except AuthenticationRequired:
            if resolved_token:
                clear_token(self.layout.update_auth)
            self._post(self._request_update_token, prompted)
            return
        except UpdateError as exc:
            self._post(self._finish_update_error, str(exc))
            return
        except BaseException as exc:
            self._post(self._finish_update_error, f"Unexpected update error: {exc}")
            return

        if offer is None:
            self._post(self._finish_no_update)
        else:
            self._post(self._confirm_update, offer, resolved_token)

    def _request_update_token(self, already_prompted: bool) -> None:
        if already_prompted:
            self._finish_update_error(
                "GitHub rejected the update token. Use a fine-grained token with read-only Contents access to this repository."
            )
            return
        token = simpledialog.askstring(
            "Private DjGoo updates",
            "This DjGoo repository is private. Enter a fine-grained GitHub token with read-only Contents access.\n\n"
            "The token will be encrypted for this Windows account and will not be written to logs.",
            show="*",
            parent=self.root,
        )
        if not token:
            self._update_busy = False
            self.log("Update check cancelled.")
            return
        try:
            save_token(self.layout.update_auth, token)
        except BaseException as exc:
            self._finish_update_error(f"Could not securely save the update token: {exc}")
            return
        threading.Thread(target=self._check_update_worker, args=(token, True), daemon=True).start()

    def _finish_no_update(self) -> None:
        self._update_busy = False
        self.log("DjGoo is already up to date.")
        messagebox.showinfo(APP_NAME, "DjGoo is already up to date.")

    def _finish_update_error(self, error: str) -> None:
        self._update_busy = False
        self.log("Update failed: " + error)
        messagebox.showerror(APP_NAME, error)

    def _confirm_update(self, offer: UpdateOffer, token: str | None) -> None:
        installed = read_installed_version(self.layout.root).text
        approved = messagebox.askyesno(
            APP_NAME,
            f"DjGoo {offer.version.text} is available.\n\n"
            f"Installed: {installed}\n"
            f"Available: {offer.version.text}\n\n"
            "Download and install the verified incremental update now?",
        )
        if not approved:
            self._update_busy = False
            self.log("Update declined.")
            return
        self.log(f"Downloading DjGoo {offer.version.text} incremental update…")
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
                self._thread_log(f"Update download: {bucket}%")

        try:
            bundle, manifest, _ = download_update(self.layout.root, offer, token, progress)
        except AuthenticationRequired:
            clear_token(self.layout.update_auth)
            self._post(self._finish_update_error, "GitHub authorization expired. Check for updates again.")
            return
        except UpdateError as exc:
            self._post(self._finish_update_error, str(exc))
            return
        except BaseException as exc:
            self._post(self._finish_update_error, f"Unexpected download error: {exc}")
            return
        self._post(self._launch_update_worker, bundle, manifest, offer)

    def _launch_update_worker(self, bundle: Path, manifest: Path, offer: UpdateOffer) -> None:
        if not self.layout.update_worker.exists():
            self._finish_update_error(f"Update worker is missing: {self.layout.update_worker}")
            return
        command = [
            str(self.layout.runtime_pythonw),
            str(self.layout.update_worker),
            "--root",
            str(self.layout.root),
            "--bundle",
            str(bundle),
            "--manifest",
            str(manifest),
            "--parent-pid",
            str(os.getpid()),
        ]
        try:
            subprocess.Popen(
                command,
                cwd=self.layout.root,
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        except OSError as exc:
            self._finish_update_error(f"Could not start the update worker: {exc}")
            return
        self.log(f"Installing DjGoo {offer.version.text}; the launcher will restart.")
        self.root.after(300, self.root.destroy)

    def _report_update_result(self) -> None:
        path = self.layout.update_result
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        try:
            path.unlink()
        except OSError:
            pass
        if bool(payload.get("success")):
            self.log(f"Update completed successfully: DjGoo {payload.get('version') or 'new version'}.")
            return
        error = str(payload.get("error") or "Unknown update error")
        self.log("Previous update failed: " + error)
        messagebox.showerror(APP_NAME, "The previous DjGoo update failed and was rolled back.\n\n" + error)

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
