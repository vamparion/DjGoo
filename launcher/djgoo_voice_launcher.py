from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    X,
    Button,
    Entry,
    Frame,
    Label,
    StringVar,
    Text,
    Tk,
    messagebox,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from voice.command_catalog import command_tip
from voice.command_parser import parse_command
from voice.command_queue import command_to_queue_item
from voice.connection_manager import (
    load_recipient_credential,
    load_recipient_transport,
    pair_from_invite,
    recipient_status,
)
from voice.pairing_bundle import parse_invite


APP_TITLE = "DjGoo Voice"
BG = "#12151c"
PANEL = "#1a1f29"
PANEL_ALT = "#202735"
TEXT = "#f1f5fb"
MUTED = "#9aa7ba"
ACCENT = "#6f8cff"
ACCENT_2 = "#9b7cff"
GOOD = "#67d49b"
WARN = "#f2c66d"
DANGER = "#f27d8a"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


class VoiceRemoteLauncher:
    def __init__(self, root: Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root
        self.runtime_python = self._first_existing(
            project_root / "runtime" / "python" / "python.exe",
            project_root / ".voice-venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        )
        self.runtime_pythonw = self._first_existing(
            project_root / "runtime" / "python" / "pythonw.exe",
            project_root / ".voice-venv" / "Scripts" / "pythonw.exe",
            self.runtime_python,
        )
        self.credential_path = project_root / "data" / "voice-remote-credential.json"
        self.settings_path = project_root / "config" / "voice-remote.json"
        self.pid_path = project_root / "data" / "voice-remote.pid"
        self.invite = StringVar()
        self.device_name = StringVar(value=os.environ.get("COMPUTERNAME", "DjGoo Voice"))
        self.hotkey = StringVar(value="F12")
        self.model = StringVar(value="distil-large-v3")
        self.microphone = StringVar()
        self.request = StringVar()
        self.status = StringVar(value="Not connected")
        self.security = StringVar(value="Paste the private invite sent by DjGoo in Discord.")
        self.tip = StringVar(value="")
        self._tip_index = 0
        self._build()
        self._load_settings()
        self.refresh_status()
        self._rotate_tip()
        self.root.after(2000, self._poll)

    @staticmethod
    def _first_existing(*paths: Path) -> Path:
        return next((path for path in paths if path.exists()), paths[-1])

    def _button(self, parent, text: str, command, *, accent: bool = False, danger: bool = False, width: int | None = None):
        background = DANGER if danger else ACCENT if accent else PANEL_ALT
        active = "#ff9aa5" if danger else "#8da2ff" if accent else "#2b3445"
        return Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=background,
            fg=TEXT,
            activebackground=active,
            activeforeground=TEXT,
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )

    def _entry(self, parent, variable: StringVar, *, show: str | None = None) -> Entry:
        return Entry(
            parent,
            textvariable=variable,
            show=show,
            bg="#0f131a",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#30394a",
            highlightcolor=ACCENT,
        )

    def _build(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("860x720")
        self.root.minsize(760, 640)
        self.root.configure(bg=BG)

        header = Frame(self.root, bg=BG, padx=22, pady=18)
        header.pack(fill=X)
        Label(header, text="DJGOO VOICE", font=("Segoe UI", 22, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        Label(
            header,
            text="Secure game-session controls. Speech recognition stays on this computer.",
            font=("Segoe UI", 10),
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        status_panel = Frame(self.root, bg=PANEL, padx=18, pady=14)
        status_panel.pack(fill=X, padx=20, pady=(0, 10))
        Label(status_panel, textvariable=self.status, font=("Segoe UI", 14, "bold"), bg=PANEL, fg=GOOD).pack(side=LEFT)
        self._button(status_panel, "Check connection", self.check_connection).pack(side=RIGHT, padx=(8, 0))
        self._button(status_panel, "Disconnect device", self.unpair, danger=True).pack(side=RIGHT)
        Label(status_panel, textvariable=self.security, font=("Segoe UI", 9), bg=PANEL, fg=MUTED).pack(anchor="w", pady=(28, 0))

        if not self.credential_path.exists():
            pairing = Frame(self.root, bg=PANEL, padx=18, pady=16)
            pairing.pack(fill=X, padx=20, pady=(0, 10))
            Label(pairing, text="Connect this player", font=("Segoe UI", 12, "bold"), bg=PANEL, fg=TEXT).pack(anchor="w")
            Label(
                pairing,
                text="In Discord, run /djgoolink pair. Copy the entire private invite and paste it here.",
                font=("Segoe UI", 9),
                bg=PANEL,
                fg=MUTED,
            ).pack(anchor="w", pady=(2, 8))
            invite_entry = self._entry(pairing, self.invite)
            invite_entry.pack(fill=X, ipady=7)
            row = Frame(pairing, bg=PANEL)
            row.pack(fill=X, pady=(10, 0))
            self._button(row, "Paste and connect", self.paste_and_pair, accent=True).pack(side=LEFT)
            self._button(row, "Connect entered invite", self.pair).pack(side=LEFT, padx=(8, 0))
            Label(row, text="One-time • expires in 5 minutes • identity pinned", bg=PANEL, fg=MUTED).pack(side=RIGHT)

        quick = Frame(self.root, bg=PANEL, padx=18, pady=14)
        quick.pack(fill=X, padx=20, pady=(0, 10))
        Label(quick, text="Quick controls", font=("Segoe UI", 12, "bold"), bg=PANEL, fg=TEXT).pack(anchor="w")
        buttons = Frame(quick, bg=PANEL)
        buttons.pack(fill=X, pady=(8, 8))
        for label, phrase in (
            ("Pause / resume", "pause"),
            ("Skip", "skip"),
            ("Queue", "queue"),
            ("Like", "like this"),
            ("More like", "more like this"),
            ("Ban", "don't play this again"),
        ):
            self._button(buttons, label, lambda p=phrase: self.send_phrase(p)).pack(side=LEFT, padx=(0, 6))
        request_row = Frame(quick, bg=PANEL)
        request_row.pack(fill=X)
        request_entry = self._entry(request_row, self.request)
        request_entry.pack(side=LEFT, fill=X, expand=True, ipady=6)
        request_entry.bind("<Return>", lambda _event: self.send_request())
        self._button(request_row, "Play next", self.send_request, accent=True).pack(side=RIGHT, padx=(8, 0))

        voice = Frame(self.root, bg=PANEL, padx=18, pady=14)
        voice.pack(fill=X, padx=20, pady=(0, 10))
        Label(voice, text="Voice control", font=("Segoe UI", 12, "bold"), bg=PANEL, fg=TEXT).grid(row=0, column=0, columnspan=4, sticky="w")
        self._field(voice, 1, "Push-to-talk", self.hotkey)
        self._field(voice, 2, "Speech model", self.model)
        self._field(voice, 3, "Microphone", self.microphone)
        controls = Frame(voice, bg=PANEL)
        controls.grid(row=4, column=1, columnspan=3, sticky="w", pady=(10, 0))
        self._button(controls, "Start listening", self.start, accent=True).pack(side=LEFT)
        self._button(controls, "Stop listening", self.stop).pack(side=LEFT, padx=(8, 0))
        self._button(controls, "Save", self.save_settings).pack(side=LEFT, padx=(8, 0))
        self._button(controls, "Microphones", self.list_microphones).pack(side=LEFT, padx=(8, 0))
        voice.columnconfigure(1, weight=1)

        coach = Frame(self.root, bg="#171c25", padx=18, pady=12)
        coach.pack(fill=X, padx=20, pady=(0, 10))
        Label(coach, text="TRY SAYING", font=("Segoe UI", 8, "bold"), bg="#171c25", fg=ACCENT_2).pack(side=LEFT)
        Label(coach, textvariable=self.tip, font=("Segoe UI", 10), bg="#171c25", fg=MUTED).pack(side=LEFT, padx=(12, 0))

        Label(self.root, text="Diagnostics", font=("Segoe UI", 9, "bold"), bg=BG, fg=MUTED, padx=20).pack(anchor="w")
        self.activity = Text(
            self.root,
            height=7,
            wrap="word",
            font=("Consolas", 9),
            bg="#0e1117",
            fg="#aeb8c8",
            insertbackground=TEXT,
            relief="flat",
        )
        self.activity.pack(fill=BOTH, expand=True, padx=20, pady=(4, 18))
        self.log("DjGoo Voice ready.")

    def _field(self, parent: Frame, row: int, label: str, variable: StringVar) -> None:
        Label(parent, text=label, width=16, anchor="w", bg=PANEL, fg=MUTED).grid(row=row, column=0, sticky="w", pady=4)
        entry = self._entry(parent, variable)
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4, ipady=5)

    def log(self, message: str) -> None:
        self.activity.insert(END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.activity.see(END)

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        voice = data.get("voice") if isinstance(data.get("voice"), dict) else data
        if isinstance(voice, dict):
            self.hotkey.set(str(voice.get("hotkey") or "F12"))
            self.model.set(str(voice.get("model") or "distil-large-v3"))
            self.microphone.set(str(voice.get("input_device") or ""))

    def save_settings(self) -> None:
        payload = {
            "voice": {
                "push_to_talk": True,
                "hotkey": self.hotkey.get().strip().upper() or "F12",
                "model": self.model.get().strip() or "distil-large-v3",
                "input_device": self.microphone.get().strip() or None,
                "feedback_beeps": True,
                "vad_filter": True,
            }
        }
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.log("Voice settings saved.")

    def paste_and_pair(self) -> None:
        try:
            self.invite.set(self.root.clipboard_get().strip())
        except Exception:
            messagebox.showerror(APP_TITLE, "The clipboard does not contain a DjGoo Link invite.")
            return
        self.pair()

    def pair(self) -> None:
        raw_invite = self.invite.get().strip()
        try:
            invite = parse_invite(raw_invite)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.status.set("Verifying secure invite…")
        self.security.set(f"Safety number {invite.safety_number()} • {len(invite.endpoints)} secure path(s)")

        def work() -> None:
            try:
                credential, transport = asyncio.run(
                    pair_from_invite(
                        invite,
                        device_name=self.device_name.get().strip() or "DjGoo Voice",
                        credential_path=self.credential_path,
                    )
                )
            except Exception as exc:
                self.root.after(0, lambda: self._pair_failed(exc))
                return
            self.root.after(0, lambda: self._pair_finished(credential, transport))

        threading.Thread(target=work, name="djgoo-link-pair", daemon=True).start()

    def _pair_finished(self, credential, transport: str) -> None:
        self.invite.set("")
        self.status.set("Connected — voice stopped")
        self.security.set(
            f"Identity verified through {transport} • credential protected for this Windows account"
        )
        self.log(f"Connected device {credential.device_id} through {transport}.")
        messagebox.showinfo(APP_TITLE, "DjGoo Voice is securely connected. Select Start listening or use the quick controls.")

    def _pair_failed(self, error: Exception) -> None:
        self.status.set("Connection failed")
        self.security.set("The invite was not accepted. It may have expired or already been used.")
        self.log(f"Connection failed: {type(error).__name__}: {error}")
        messagebox.showerror(APP_TITLE, str(error))

    def check_connection(self) -> None:
        if not self.credential_path.exists():
            messagebox.showerror(APP_TITLE, "Connect this device first.")
            return
        self.status.set("Checking secure connection…")

        def work() -> None:
            try:
                result = recipient_status(self.credential_path)
            except Exception as exc:
                self.root.after(0, lambda: self._connection_failed(exc))
                return
            self.root.after(0, lambda: self._connection_ok(result))

        threading.Thread(target=work, name="djgoo-link-check", daemon=True).start()

    def _connection_ok(self, result: dict) -> None:
        mode = str(result.get("transport") or "secure")
        self.status.set(f"Connected through {mode}")
        self.security.set("Host identity verified • device token active • microphone audio remains local")
        self.log("Secure connection check passed.")

    def _connection_failed(self, error: Exception) -> None:
        self.status.set("Host unavailable")
        self.security.set("DjGoo will keep the device credential and can reconnect when the Host returns.")
        self.log(f"Connection check failed: {type(error).__name__}: {error}")

    def _send_item(self, item: dict) -> None:
        if not self.credential_path.exists():
            messagebox.showerror(APP_TITLE, "Connect this device first.")
            return

        def work() -> None:
            try:
                transport = load_recipient_transport(self.credential_path)
                result = transport.send(item)
            except Exception as exc:
                self.root.after(0, lambda: self._command_failed(exc))
                return
            self.root.after(0, lambda: self._command_ok(item, result))

        threading.Thread(target=work, name="djgoo-quick-control", daemon=True).start()

    def send_phrase(self, phrase: str) -> None:
        command = parse_command(phrase, require_wake=False)
        item = command_to_queue_item(command, transcript=phrase, source="voice_remote")
        self._send_item(item)

    def send_request(self) -> None:
        query = self.request.get().strip()
        if not query:
            return
        self.request.set("")
        self.send_phrase(f"play {query}")

    def _command_ok(self, item: dict, result: dict) -> None:
        intent = str(item.get("intent") or "command").replace("_", " ")
        duplicate = " duplicate-safe retry" if result.get("duplicate") else ""
        self.log(f"{intent.title()} accepted.{duplicate}")

    def _command_failed(self, error: Exception) -> None:
        self.log(f"Control failed: {type(error).__name__}: {error}")
        self.status.set("Control could not reach Host")

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
                "voice.djgoo_voice_remote",
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

    def _running_pid(self) -> int | None:
        try:
            pid = int(self.pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if str(pid) in result.stdout:
                return pid
        else:
            try:
                os.kill(pid, 0)
                return pid
            except OSError:
                pass
        self.pid_path.unlink(missing_ok=True)
        return None

    def stop(self) -> None:
        pid = self._running_pid()
        if pid is None:
            self.log("Voice control is not running.")
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.kill(pid, signal.SIGTERM)
        self.pid_path.unlink(missing_ok=True)
        self.log("Voice control stopped.")
        self.refresh_status()

    def unpair(self) -> None:
        if not self.credential_path.exists():
            return
        if self._running_pid() is not None:
            self.stop()
        if not messagebox.askyesno(APP_TITLE, "Remove this device credential? The Discord user can pair it again later."):
            return
        self.credential_path.unlink(missing_ok=True)
        self.status.set("Not connected")
        self.security.set("Request a new private invite with /djgoolink pair.")
        self.log("Device credential removed.")

    def list_microphones(self) -> None:
        subprocess.Popen(
            [
                str(self.runtime_python),
                "-c",
                "import sounddevice as sd; print(sd.query_devices()); input('Press Enter to close...')",
            ],
            cwd=self.project_root,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )

    def refresh_status(self) -> None:
        if not self.credential_path.exists():
            self.status.set("Not connected")
            return
        try:
            credential = load_recipient_credential(self.credential_path)
            mode = credential.transport
        except Exception:
            self.status.set("Credential needs attention")
            return
        if self._running_pid() is not None:
            self.status.set(f"Listening on {self.hotkey.get().strip().upper() or 'F12'} • {mode}")
        else:
            self.status.set(f"Connected through {mode} — voice stopped")
        self.security.set("Pinned Host identity • individually revocable device • Windows-protected credential")

    def _rotate_tip(self) -> None:
        hint = command_tip(self._tip_index)
        self._tip_index += 1
        self.tip.set(f"“{hint.phrase}”  —  {hint.description}")
        self.root.after(8000, self._rotate_tip)

    def _poll(self) -> None:
        self.refresh_status()
        self.root.after(2000, self._poll)


def main() -> int:
    root = Tk()
    VoiceRemoteLauncher(root, application_root())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
