from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Button, Entry, Frame, Label, StringVar, Text, Tk, messagebox


APP_TITLE = "DjGoo Voice Remote"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


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
        self.gateway = StringVar()
        self.code = StringVar()
        self.fingerprint = StringVar()
        self.device_name = StringVar(value=os.environ.get("COMPUTERNAME", "DjGoo Voice Remote"))
        self.hotkey = StringVar(value="F12")
        self.model = StringVar(value="distil-large-v3")
        self.microphone = StringVar()
        self.status = StringVar(value="Not paired")
        self._build()
        self._load_settings()
        self.refresh_status()
        self.root.after(2000, self._poll)

    @staticmethod
    def _first_existing(*paths: Path) -> Path:
        return next((path for path in paths if path.exists()), paths[-1])

    def _build(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("760x620")
        self.root.minsize(700, 560)

        header = Frame(self.root, padx=18, pady=14)
        header.pack(fill=X)
        Label(header, text="DjGoo Voice", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        Label(
            header,
            text="Local speech recognition for a paired DjGoo Host",
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        pairing = Frame(self.root, padx=18, pady=8)
        pairing.pack(fill=X)
        Label(pairing, text="Pairing", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        self._field(pairing, 1, "Gateway URL", self.gateway)
        self._field(pairing, 2, "Pairing code", self.code)
        self._field(pairing, 3, "TLS fingerprint", self.fingerprint)
        self._field(pairing, 4, "Device name", self.device_name)
        Button(pairing, text="Pair device", command=self.pair).grid(row=5, column=1, sticky="w", pady=(8, 0))
        pairing.columnconfigure(1, weight=1)

        settings = Frame(self.root, padx=18, pady=8)
        settings.pack(fill=X)
        Label(settings, text="Voice settings", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        self._field(settings, 1, "Push-to-talk key", self.hotkey)
        self._field(settings, 2, "Whisper model", self.model)
        self._field(settings, 3, "Microphone name", self.microphone)
        Button(settings, text="Save settings", command=self.save_settings).grid(row=4, column=1, sticky="w", pady=(8, 0))
        Button(settings, text="List microphones", command=self.list_microphones).grid(row=4, column=1, sticky="w", padx=(110, 0), pady=(8, 0))
        settings.columnconfigure(1, weight=1)

        controls = Frame(self.root, padx=18, pady=10)
        controls.pack(fill=X)
        Label(controls, text="Status:", font=("Segoe UI", 10, "bold")).pack(side=LEFT)
        Label(controls, textvariable=self.status).pack(side=LEFT, padx=(8, 16))
        Button(controls, text="Start voice", width=14, command=self.start).pack(side=LEFT, padx=(0, 8))
        Button(controls, text="Stop voice", width=14, command=self.stop).pack(side=LEFT, padx=(0, 8))
        Button(controls, text="Open logs", command=self.open_logs).pack(side=RIGHT)

        self.activity = Text(self.root, height=12, wrap="word", font=("Consolas", 9))
        self.activity.pack(fill=BOTH, expand=True, padx=18, pady=(0, 18))
        self.log("Voice Remote launcher ready.")

    @staticmethod
    def _field(parent: Frame, row: int, label: str, variable: StringVar) -> None:
        Label(parent, text=label, width=18, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
        Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)

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

    def pair(self) -> None:
        values = (self.gateway.get().strip(), self.code.get().strip(), self.fingerprint.get().strip())
        if not all(values):
            messagebox.showerror(APP_TITLE, "Gateway URL, pairing code, and TLS fingerprint are required.")
            return
        self.status.set("Pairing…")

        def work() -> None:
            command = [
                str(self.runtime_python),
                "-m",
                "voice.djgoo_voice_remote",
                "--project-root",
                str(self.project_root),
                "pair",
                "--gateway",
                values[0],
                "--code",
                values[1],
                "--fingerprint",
                values[2],
                "--device-name",
                self.device_name.get().strip() or "DjGoo Voice Remote",
            ]
            result = subprocess.run(command, cwd=self.project_root, capture_output=True, text=True)
            self.root.after(0, lambda: self._pair_finished(result))

        threading.Thread(target=work, name="djgoo-pair", daemon=True).start()

    def _pair_finished(self, result: subprocess.CompletedProcess[str]) -> None:
        if result.returncode == 0:
            self.log(result.stdout.strip() or "Device paired.")
            self.code.set("")
            self.status.set("Paired — stopped")
        else:
            detail = result.stderr.strip() or result.stdout.strip() or "Unknown pairing error"
            self.log("Pairing failed: " + detail)
            self.status.set("Pairing failed")
            messagebox.showerror(APP_TITLE, detail)

    def start(self) -> None:
        if not self.credential_path.exists():
            messagebox.showerror(APP_TITLE, "Pair this device before starting voice control.")
            return
        if self._running_pid() is not None:
            self.log("Voice Remote is already running.")
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
        self.log(f"Voice Remote started as process {process.pid}.")
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
            self.log("Voice Remote is not running.")
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
        self.log("Voice Remote stopped.")
        self.refresh_status()

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
            self.status.set("Not paired")
        elif self._running_pid() is not None:
            self.status.set("Paired — listening for F12")
        else:
            self.status.set("Paired — stopped")

    def _poll(self) -> None:
        self.refresh_status()
        self.root.after(2000, self._poll)

    def open_logs(self) -> None:
        logs = self.project_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(logs)


def main() -> int:
    root = Tk()
    VoiceRemoteLauncher(root, application_root())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
