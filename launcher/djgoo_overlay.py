from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Button, Entry, Frame, Label, StringVar, Tk


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from voice.command_parser import parse_command
from voice.command_queue import append_queue_item, command_to_queue_item
from voice.now_playing_state import NowPlayingState


BG = "#101319"
PANEL = "#171c25"
TEXT = "#f2f5fa"
MUTED = "#9aa7ba"
ACCENT = "#728cff"
DANGER = "#e96f7d"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


class DjGooMiniPlayer:
    def __init__(self, root: Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root
        self.state = NowPlayingState(project_root / "data" / "djgoo-now-playing.json")
        self.queue_path = project_root / "data" / "voice-command-queue.jsonl"
        self.title = StringVar(value="DjGoo is waiting for music")
        self.detail = StringVar(value="Start a radio station or request a song in Discord.")
        self.progress = StringVar(value="")
        self.tip = StringVar(value="Try saying: “radio balanced 2000s rock”")
        self.request = StringVar()
        self._started_at = 0.0
        self._duration = 0
        self._build()
        self._poll()

    def _button(self, parent, text: str, command, *, danger: bool = False):
        return Button(
            parent,
            text=text,
            command=command,
            bg=DANGER if danger else "#242c3a",
            fg=TEXT,
            activebackground="#344056",
            activeforeground=TEXT,
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        )

    def _build(self) -> None:
        self.root.title("DjGoo Mini Player")
        self.root.geometry("470x210")
        self.root.minsize(420, 190)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)

        header = Frame(self.root, bg=BG, padx=14, pady=10)
        header.pack(fill=X)
        Label(header, text="● DJGOO", font=("Segoe UI", 9, "bold"), bg=BG, fg=ACCENT).pack(side=LEFT)
        Label(header, textvariable=self.progress, font=("Segoe UI", 9), bg=BG, fg=MUTED).pack(side=RIGHT)

        now = Frame(self.root, bg=PANEL, padx=14, pady=10)
        now.pack(fill=X, padx=10)
        Label(now, textvariable=self.title, font=("Segoe UI", 13, "bold"), bg=PANEL, fg=TEXT, anchor="w").pack(fill=X)
        Label(now, textvariable=self.detail, font=("Segoe UI", 9), bg=PANEL, fg=MUTED, anchor="w").pack(fill=X, pady=(3, 0))
        Label(now, textvariable=self.tip, font=("Segoe UI", 8), bg=PANEL, fg="#b2bce0", anchor="w").pack(fill=X, pady=(6, 0))

        controls = Frame(self.root, bg=BG, padx=10, pady=8)
        controls.pack(fill=X)
        for label, phrase in (
            ("Pause", "pause"),
            ("Skip", "skip"),
            ("Like", "like this"),
            ("More", "more like this"),
            ("Ban", "don't play this again"),
        ):
            self._button(controls, label, lambda p=phrase: self.send(p), danger=label == "Ban").pack(side=LEFT, padx=(0, 5))

        request_row = Frame(self.root, bg=BG, padx=10, pady=(0, 10))
        request_row.pack(fill=BOTH, expand=True)
        entry = Entry(
            request_row,
            textvariable=self.request,
            bg="#0d1016",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
        )
        entry.pack(side=LEFT, fill=X, expand=True, ipady=5)
        entry.bind("<Return>", lambda _event: self.play_request())
        self._button(request_row, "Play next", self.play_request).pack(side=RIGHT, padx=(7, 0))

    def send(self, phrase: str) -> None:
        command = parse_command(phrase, require_wake=False)
        item = command_to_queue_item(
            command,
            transcript=phrase,
            source="overlay",
        )
        append_queue_item(self.queue_path, item)

    def play_request(self) -> None:
        query = self.request.get().strip()
        if not query:
            return
        self.request.set("")
        self.send(f"play {query}")

    def _poll(self) -> None:
        payload = self.state.latest()
        if payload is not None:
            mode = str(payload.get("mode") or "PLAYBACK")
            title = str(payload.get("title") or "Unknown track")
            artist = str(payload.get("artist") or "").strip()
            station = str(payload.get("station") or "").strip()
            queue = payload.get("queue") if isinstance(payload.get("queue"), list) else []
            detail_parts = [mode]
            if station:
                detail_parts.append(station)
            if artist:
                detail_parts.append(artist)
            if queue:
                detail_parts.append(f"Next: {queue[0]}")
            self.title.set(title)
            self.detail.set(" • ".join(detail_parts))
            self.tip.set(str(payload.get("tip") or ""))
            self._started_at = float(payload.get("started_at") or 0)
            self._duration = int(payload.get("duration_seconds") or 0)
        elapsed = max(0, int(time.time() - self._started_at)) if self._started_at else 0
        if self._duration:
            elapsed = min(elapsed, self._duration)
            self.progress.set(
                f"{elapsed // 60}:{elapsed % 60:02d} / {self._duration // 60}:{self._duration % 60:02d}"
            )
        else:
            self.progress.set("")
        self.root.after(500, self._poll)


def main() -> int:
    root = Tk()
    DjGooMiniPlayer(root, application_root())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
