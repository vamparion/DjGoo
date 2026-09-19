from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    X,
    Y,
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    DoubleVar,
    Entry,
    Frame,
    Label,
    Listbox,
    StringVar,
    Tk,
    Toplevel,
)
from tkinter import ttk
from typing import Any, BinaryIO, Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from voice.command_queue import append_queue_item
from voice.mini_player_protocol import CommandReceiptStore, mini_player_command
from voice.now_playing_state import NowPlayingState


BG = "#090d10"
PANEL = "#11181d"
PANEL_2 = "#182229"
PANEL_3 = "#202c34"
TEXT = "#edf7f4"
MUTED = "#8b9ca1"
ACCENT = "#35d2bd"
ACCENT_HOVER = "#52e1ce"
BLUE = "#6591ff"
BLUE_HOVER = "#7ca2ff"
GOOD = "#7bd88f"
DANGER = "#ff667b"
DANGER_HOVER = "#ff7b8d"
WARN = "#f0c45c"
BORDER = "#27343a"
ENTRY_BG = "#0c1216"
DISABLED = "#526168"
COMPACT_WIDTH = 540
COMPACT_HEIGHT = 238
EXPANDED_WIDTH = 1040
EXPANDED_HEIGHT = 560


try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def format_time(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


class Tooltip:
    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.window is not None:
            return
        self.window = Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.configure(bg=BORDER)
        self.window.geometry(
            f"+{self.widget.winfo_rootx()}+"
            f"{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}"
        )
        Label(
            self.window,
            text=self.text,
            bg=PANEL_2,
            fg=TEXT,
            font=("Segoe UI", 8),
            padx=7,
            pady=4,
        ).pack(padx=1, pady=1)

    def _hide(self, _event=None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class JsonSettings:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        value = read_json(self.path, {})
        return value if isinstance(value, dict) else {}

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class SingleMiniPlayer:
    """Keep repeated launcher clicks from opening competing player windows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    self.handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except (OSError, BlockingIOError):
            self.handle.close()
            self.handle = None
            return False
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


class DjGooMiniPlayer:
    def __init__(self, root: Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root
        self.state = NowPlayingState(project_root / "data" / "djgoo-now-playing.json")
        self.queue_path = project_root / "data" / "voice-command-queue.jsonl"
        self.receipts = CommandReceiptStore(project_root / "data" / "mini-player-acks")
        self.settings_store = JsonSettings(project_root / "data" / "mini-player-settings.json")
        self.settings = self.settings_store.read()

        self.title = StringVar(value="DjGoo is waiting for music")
        self.detail = StringVar(value="Ready for a song, playlist, or radio station")
        self.progress_text = StringVar(value="0:00 / 0:00")
        self.status = StringVar(value="Waiting for DjGoo")
        self.request = StringVar()
        self.queue_summary = StringVar(value="Queue is empty")
        self.radio_summary = StringVar(value="Radio off")
        self.station_mode = StringVar(value="Balanced")
        self.playlist_name = StringVar()
        self.new_playlist_name = StringVar()
        self.expanded_station = StringVar(value="No active station")
        self.expanded_next = StringVar(value="Nothing queued")
        self.expanded_health = StringVar(value="Waiting for component health")
        self.volume_value = DoubleVar(value=100)
        self.always_on_top = BooleanVar(
            value=bool(self.settings.get("always_on_top", True))
        )

        self._payload: dict[str, Any] = {}
        self._queue_fingerprint = ""
        self._history_fingerprint = ""
        self._playlist_fingerprint = ""
        self._preferred_playlist = ""
        self._search_results: list[dict[str, Any]] = []
        self._expanded_history: list[dict[str, Any]] = []
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_keys: set[str] = set()
        self._queued_search_query = ""
        self._search_after: str | None = None
        self._drawer_open = False
        self._drag_item = ""
        self._drag_changed = False
        self._last_artwork_url = ""
        self._artwork_photo = None
        self._tree_artwork: dict[str, Any] = {}
        self._tree_artwork_loading: set[str] = set()
        self._core_buttons: list[Button] = []
        self._radio_controls: list[Any] = []
        self._last_position_save = 0.0
        self._closing = False

        self._configure_styles()
        self._build()
        self._restore_position()
        self._set_topmost()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Configure>", self._remember_position, add="+")
        self._poll()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        with contextlib.suppress(Exception):
            style.theme_use("clam")
        style.configure(
            "DjGoo.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=36,
            borderwidth=1,
            relief="flat",
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            font=("Segoe UI", 9),
        )
        style.configure(
            "DjGoo.Treeview.Heading",
            background=PANEL_3,
            foreground="#b9c7c9",
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 8),
            padding=(7, 6),
        )
        style.map(
            "DjGoo.Treeview",
            background=[("selected", "#1f5e5a")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "DjGoo.TNotebook",
            background=PANEL,
            borderwidth=0,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "DjGoo.TNotebook.Tab",
            background="#0e1519",
            foreground=MUTED,
            padding=(14, 8),
            borderwidth=0,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "DjGoo.TNotebook.Tab",
            background=[("selected", PANEL_3), ("active", PANEL_2)],
            foreground=[("selected", ACCENT), ("active", TEXT)],
        )
        style.configure(
            "DjGoo.Horizontal.TProgressbar",
            troughcolor=ENTRY_BG,
            background=ACCENT,
            borderwidth=0,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        style.configure(
            "DjGoo.Horizontal.TScale",
            background=BG,
            troughcolor=ENTRY_BG,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            sliderrelief="flat",
        )
        style.configure(
            "DjGoo.TCombobox",
            fieldbackground=PANEL_2,
            background=PANEL_2,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=3,
        )
        style.map(
            "DjGoo.TCombobox",
            fieldbackground=[("readonly", PANEL_2), ("disabled", PANEL)],
            foreground=[("readonly", TEXT), ("disabled", DISABLED)],
            arrowcolor=[("readonly", ACCENT), ("disabled", DISABLED)],
        )
        style.configure(
            "DjGoo.Vertical.TScrollbar",
            background=PANEL_3,
            troughcolor=ENTRY_BG,
            bordercolor=ENTRY_BG,
            arrowcolor=MUTED,
            relief="flat",
        )

    def _button(
        self,
        parent,
        text: str,
        command: Callable[[], None],
        *,
        danger: bool = False,
        accent: bool = False,
        variant: str = "neutral",
        width: int | None = None,
        tooltip: str = "",
        core: bool = True,
    ) -> Button:
        if danger:
            variant = "danger"
        elif accent:
            variant = "primary"
        palette = {
            "neutral": (PANEL_3, "#2d3c45", TEXT),
            "primary": (ACCENT, ACCENT_HOVER, "#07110f"),
            "blue": (BLUE, BLUE_HOVER, "#081025"),
            "good": (GOOD, "#92e5a2", "#08130b"),
            "danger": (DANGER, DANGER_HOVER, "#19080b"),
            "warn": (WARN, "#f6d477", "#171104"),
        }
        normal_bg, hover_bg, foreground = palette.get(variant, palette["neutral"])
        button = Button(
            parent,
            text=text,
            command=command,
            bg=normal_bg,
            fg=foreground,
            disabledforeground=DISABLED,
            activebackground=hover_bg,
            activeforeground=foreground,
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            width=width or 0,
            cursor="hand2",
            font=("Segoe UI Semibold", 8),
            highlightthickness=0,
        )
        button._djgoo_normal_bg = normal_bg  # type: ignore[attr-defined]
        button.bind(
            "<Enter>",
            lambda _event: button.configure(bg=hover_bg)
            if str(button.cget("state")) != "disabled"
            else None,
            add="+",
        )
        button.bind(
            "<Leave>",
            lambda _event: button.configure(
                bg=normal_bg
                if str(button.cget("state")) != "disabled"
                else PANEL_2
            ),
            add="+",
        )
        if core:
            self._core_buttons.append(button)
        if tooltip:
            Tooltip(button, tooltip)
        return button

    def _build(self) -> None:
        self.root.title("DjGoo Mini Player")
        self.root.geometry(f"{COMPACT_WIDTH}x{COMPACT_HEIGHT}")
        self.root.minsize(500, COMPACT_HEIGHT)
        self.root.configure(bg=BG)

        self.compact = Frame(
            self.root,
            bg=BG,
            width=COMPACT_WIDTH,
            height=COMPACT_HEIGHT,
        )
        self.compact.pack(side=LEFT, fill=BOTH, expand=True)
        self.compact.pack_propagate(False)

        header = Frame(self.compact, bg=BG, padx=10, pady=5)
        header.pack(fill=X)
        brand_mark = Canvas(
            header,
            width=22,
            height=18,
            bg=BG,
            highlightthickness=0,
        )
        brand_mark.pack(side=LEFT, padx=(0, 6))
        for x, height, color in (
            (2, 7, BLUE),
            (7, 13, ACCENT),
            (12, 17, WARN),
            (17, 10, DANGER),
        ):
            brand_mark.create_rectangle(
                x,
                18 - height,
                x + 3,
                18,
                fill=color,
                outline="",
            )
        Label(
            header,
            text="DJGOO",
            font=("Segoe UI Semibold", 11),
            bg=BG,
            fg=TEXT,
        ).pack(side=LEFT)
        Label(
            header,
            text="  MINI PLAYER",
            font=("Segoe UI Semibold", 7),
            bg=BG,
            fg=ACCENT,
        ).pack(side=LEFT, pady=(3, 0))
        self.health_canvas = Canvas(
            header,
            width=57,
            height=14,
            bg=BG,
            highlightthickness=0,
        )
        self.health_canvas.pack(side=RIGHT, padx=(7, 0))
        Tooltip(self.health_canvas, "Discord / Music Core / Voice health")
        Checkbutton(
            header,
            text="Top",
            variable=self.always_on_top,
            command=self._set_topmost,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL,
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        ).pack(side=RIGHT)

        now_shell = Frame(self.compact, bg=BORDER, height=60)
        now_shell.pack(fill=X, padx=10)
        now_shell.pack_propagate(False)
        now = Frame(now_shell, bg=PANEL, height=58)
        now.pack(fill=BOTH, expand=True, padx=1, pady=1)
        now.pack_propagate(False)
        self.artwork = Label(
            now,
            bg=ENTRY_BG,
            fg=ACCENT,
            text="DG",
            font=("Segoe UI Semibold", 13),
            width=7,
        )
        self.artwork.pack(side=LEFT, fill=Y)
        now_text = Frame(now, bg=PANEL, padx=9, pady=6)
        now_text.pack(side=LEFT, fill=BOTH, expand=True)
        Label(
            now_text,
            textvariable=self.title,
            font=("Segoe UI Semibold", 11),
            bg=PANEL,
            fg=TEXT,
            anchor="w",
        ).pack(fill=X)
        Label(
            now_text,
            textvariable=self.detail,
            font=("Segoe UI", 8),
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).pack(fill=X, pady=(2, 0))
        self.queue_button = self._button(
            now,
            "Queue 0",
            self.toggle_drawer,
            variant="blue",
            width=8,
            tooltip="Open the queue and library drawer",
            core=False,
        )
        self.queue_button.pack(side=RIGHT, padx=8)

        progress_row = Frame(self.compact, bg=BG, padx=10, pady=3)
        progress_row.pack(fill=X)
        self.progress_bar = ttk.Progressbar(
            progress_row,
            style="DjGoo.Horizontal.TProgressbar",
            maximum=100,
        )
        self.progress_bar.pack(side=LEFT, fill=X, expand=True)
        Label(
            progress_row,
            textvariable=self.progress_text,
            font=("Segoe UI", 8),
            bg=BG,
            fg=MUTED,
            width=13,
            anchor="e",
        ).pack(side=RIGHT, padx=(7, 0))

        controls = Frame(self.compact, bg=BG, padx=10)
        controls.pack(fill=X)
        self.pause_button = self._button(
            controls,
            "Pause",
            self._toggle_pause,
            width=6,
            variant="primary",
            tooltip="Pause or resume playback",
        )
        self.pause_button.pack(side=LEFT, padx=(0, 4))
        for label, intent, tip, variant in (
            ("Replay", "replay", "Restart the current track", "neutral"),
            ("Skip", "skip", "Skip to the next track", "blue"),
            ("Stop", "stop", "Stop playback and radio", "danger"),
            ("Vol -", "volume_down", "Lower volume", "neutral"),
            ("Vol +", "volume_up", "Raise volume", "neutral"),
            ("Mute", "mini_mute", "Mute or restore volume", "neutral"),
            ("Fav", "favorite_current", "Add the current song to Favorites", "warn"),
        ):
            self._button(
                controls,
                label,
                lambda value=intent, key=label: self.send(
                    value,
                    pending_key=f"control:{key}",
                ),
                variant=variant,
                width=5,
                tooltip=tip,
            ).pack(side=LEFT, padx=(0, 4))

        self.radio_row = Frame(self.compact, bg=BG, padx=10, pady=3)
        self.radio_row.pack(fill=X)
        self.radio_label = Label(
            self.radio_row,
            textvariable=self.radio_summary,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            width=15,
        )
        self.radio_label.pack(side=LEFT)
        for label, intent, tip, variant in (
            ("Like", "station_like_current", "Like this song for this station", "good"),
            ("More", "station_more_like_current", "Play more songs like this", "primary"),
            ("Less", "station_less_like_current", "Play fewer songs like this", "warn"),
            ("Ban", "station_ban_current", "Never play this song on this station", "danger"),
            ("Undo", "undo_station_ban", "Undo the most recent station ban", "neutral"),
        ):
            button = self._button(
                self.radio_row,
                label,
                lambda value=intent: self.send(
                    value,
                    pending_key=f"radio:{value}",
                ),
                variant=variant,
                width=4,
                tooltip=tip,
            )
            button.pack(side=LEFT, padx=(0, 3))
            self._radio_controls.append(button)
        self.mode_combo = ttk.Combobox(
            self.radio_row,
            textvariable=self.station_mode,
            values=("Bangers", "Balanced", "Discovery", "Throwbacks"),
            state="readonly",
            width=9,
            style="DjGoo.TCombobox",
        )
        self.mode_combo.pack(side=LEFT, padx=(2, 3))
        self.mode_combo.bind("<<ComboboxSelected>>", self._change_radio_mode)
        self._radio_controls.append(self.mode_combo)
        self.stop_radio_button = self._button(
            self.radio_row,
            "Stop Radio",
            lambda: self.send("mini_stop_radio", pending_key="radio:stop"),
            width=8,
            variant="danger",
            tooltip="Stop radio additions but preserve requested songs",
        )
        self.stop_radio_button.pack(side=RIGHT)
        self._radio_controls.append(self.stop_radio_button)

        request_row = Frame(self.compact, bg=BG, padx=10)
        request_row.pack(fill=X)
        request_shell = Frame(request_row, bg=BORDER)
        request_shell.pack(side=LEFT, fill=X, expand=True)
        self.request_entry = Entry(
            request_shell,
            textvariable=self.request,
            bg=ENTRY_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        )
        self.request_entry.pack(fill=X, expand=True, padx=1, pady=1, ipady=4)
        self.request_entry.bind(
            "<Return>",
            lambda _event: self.play_request("next"),
        )
        self.request_entry.bind("<KeyRelease>", self._schedule_search)
        self.request_entry.bind(
            "<FocusIn>",
            lambda _event: request_shell.configure(bg=ACCENT),
            add="+",
        )
        self.request_entry.bind(
            "<FocusOut>",
            lambda _event: request_shell.configure(bg=BORDER),
            add="+",
        )
        for label, timing, variant in (
            ("Later", "later", "neutral"),
            ("Next", "next", "primary"),
            ("Now", "now", "danger"),
        ):
            self._button(
                request_row,
                label,
                lambda value=timing: self.play_request(value),
                variant=variant,
                width=4,
                tooltip=f"Play {timing}",
            ).pack(side=RIGHT, padx=(5, 0))

        status_row = Frame(self.compact, bg=BG, padx=10, pady=3)
        status_row.pack(fill=X)
        self.status_canvas = Canvas(
            status_row,
            width=11,
            height=11,
            bg=BG,
            highlightthickness=0,
        )
        self.status_canvas.pack(side=LEFT, padx=(0, 5))
        self.status_dot = self.status_canvas.create_oval(
            2,
            2,
            9,
            9,
            fill=MUTED,
            outline="",
        )
        self.status_label = Label(
            status_row,
            textvariable=self.status,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.status_label.pack(side=LEFT, fill=X, expand=True)

        self._build_expanded_session()

        self.drawer = Frame(self.root, bg=PANEL, width=500)
        self._build_drawer()

    def _build_expanded_session(self) -> None:
        panel = Frame(self.compact, bg=BG, padx=10, pady=12)
        panel.pack(fill=BOTH, expand=True)
        Label(
            panel,
            text="SESSION",
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill=X)
        Label(
            panel,
            textvariable=self.expanded_station,
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
            anchor="w",
            wraplength=500,
        ).pack(fill=X, pady=(8, 2))
        Label(
            panel,
            textvariable=self.expanded_next,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=500,
        ).pack(fill=X)
        Label(
            panel,
            textvariable=self.expanded_health,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill=X, pady=(4, 10))

        volume = Frame(panel, bg=BG)
        volume.pack(fill=X)
        Label(
            volume,
            text="Volume",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            width=8,
            anchor="w",
        ).pack(side=LEFT)
        self.volume_scale = ttk.Scale(
            volume,
            from_=0,
            to=150,
            variable=self.volume_value,
            style="DjGoo.Horizontal.TScale",
        )
        self.volume_scale.pack(side=LEFT, fill=X, expand=True)
        self.volume_scale.bind("<ButtonRelease-1>", self._set_volume)
        self.volume_label = Label(
            volume,
            text="100",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 8),
            width=4,
            anchor="e",
        )
        self.volume_label.pack(side=RIGHT)
        self.volume_scale.configure(
            command=lambda value: self.volume_label.configure(
                text=str(round(float(value)))
            )
        )

        recent_header = Frame(panel, bg=BG, pady=10)
        recent_header.pack(fill=X)
        Label(
            recent_header,
            text="RECENTLY PLAYED",
            bg=BG,
            fg=ACCENT,
            font=("Segoe UI Semibold", 9),
        ).pack(side=LEFT)
        self.expanded_recent = Listbox(
            panel,
            bg=PANEL,
            fg=TEXT,
            selectbackground="#1f5e5a",
            selectforeground=TEXT,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            height=5,
            exportselection=False,
            font=("Segoe UI", 9),
        )
        self.expanded_recent.pack(fill=BOTH, expand=True)
        self.expanded_recent.bind(
            "<Double-1>",
            lambda _event: self._play_expanded_recent(),
        )

    def _build_drawer(self) -> None:
        drawer_header = Frame(self.drawer, bg=PANEL, padx=10, pady=8)
        drawer_header.pack(fill=X)
        Label(
            drawer_header,
            text="DJGOO LIBRARY",
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI Semibold", 10),
        ).pack(side=LEFT)
        self._button(
            drawer_header,
            "Close",
            self.toggle_drawer,
            width=6,
            variant="neutral",
            core=False,
        ).pack(side=RIGHT)

        self.tabs = ttk.Notebook(self.drawer, style="DjGoo.TNotebook")
        self.tabs.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        self.queue_tab = Frame(self.tabs, bg=PANEL)
        self.search_tab = Frame(self.tabs, bg=PANEL)
        self.history_tab = Frame(self.tabs, bg=PANEL)
        self.playlists_tab = Frame(self.tabs, bg=PANEL)
        self.tabs.add(self.queue_tab, text="Queue")
        self.tabs.add(self.search_tab, text="Search Results")
        self.tabs.add(self.history_tab, text="History")
        self.tabs.add(self.playlists_tab, text="Playlists")
        self._build_queue_tab()
        self._build_search_tab()
        self._build_history_tab()
        self._build_playlists_tab()

    def _tree(
        self,
        parent,
        columns: tuple[str, ...],
        headings: tuple[str, ...],
        widths: tuple[int, ...],
        *,
        selectmode: str = "extended",
        hidden: tuple[str, ...] = (),
        with_images: bool = False,
    ) -> ttk.Treeview:
        tree = ttk.Treeview(
            parent,
            columns=columns,
            show="tree headings" if with_images else "headings",
            style="DjGoo.Treeview",
            selectmode=selectmode,
        )
        if with_images:
            tree.heading("#0", text="")
            tree.column("#0", width=34, minwidth=34, stretch=False)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(
                column,
                width=0 if column in hidden else width,
                minwidth=0 if column in hidden else 45,
                stretch=column in {"title", "name"},
            )
        scrollbar = ttk.Scrollbar(
            parent,
            orient=VERTICAL,
            command=tree.yview,
            style="DjGoo.Vertical.TScrollbar",
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        return tree

    def _build_queue_tab(self) -> None:
        summary = Frame(self.queue_tab, bg=PANEL, pady=6)
        summary.pack(fill=X)
        Label(
            summary,
            textvariable=self.queue_summary,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(side=LEFT)
        tools = Frame(summary, bg=PANEL)
        tools.pack(side=RIGHT)
        for label, action, tip in (
            (
                "Shuffle Requests",
                self._shuffle_requests,
                "Shuffle requests while preserving the radio lane",
            ),
            (
                "Undo",
                lambda: self.send("mini_queue_undo", pending_key="queue:undo"),
                "Undo the most recent queue edit",
            ),
            ("Clear", self._clear_queue, "Clear every queued track"),
        ):
            self._button(
                tools,
                label,
                action,
                variant="danger" if label == "Clear" else "neutral",
                tooltip=tip,
            ).pack(side=LEFT, padx=(4, 0))
        body = Frame(self.queue_tab, bg=PANEL)
        body.pack(fill=BOTH, expand=True)
        self.queue_tree = self._tree(
            body,
            ("title", "duration", "requester", "type"),
            ("Track", "Time", "Requested by", "Lane"),
            (240, 55, 95, 70),
            with_images=True,
        )
        self.queue_tree.bind("<ButtonPress-1>", self._queue_drag_start, add="+")
        self.queue_tree.bind("<B1-Motion>", self._queue_drag_motion, add="+")
        self.queue_tree.bind("<ButtonRelease-1>", self._queue_drag_end, add="+")
        self.queue_tree.bind(
            "<Delete>",
            lambda _event: self._queue_action("mini_queue_remove_many"),
            add="+",
        )
        self.queue_tree.bind(
            "<Double-1>",
            lambda _event: self._queue_action("mini_queue_play_now"),
        )

        actions = Frame(self.queue_tab, bg=PANEL, pady=7)
        actions.pack(fill=X)
        for label, intent in (
            ("Play Now", "mini_queue_play_now"),
            ("Move Next", "mini_queue_move_next"),
            ("Remove", "mini_queue_remove_many"),
        ):
            self._button(
                actions,
                label,
                lambda value=intent: self._queue_action(value),
                variant=(
                    "primary"
                    if label == "Play Now"
                    else "danger"
                    if label == "Remove"
                    else "blue"
                ),
            ).pack(side=LEFT, padx=(0, 5))
        self.queue_playlist_combo = ttk.Combobox(
            actions,
            textvariable=self.playlist_name,
            state="readonly",
            width=17,
            style="DjGoo.TCombobox",
        )
        self.queue_playlist_combo.pack(side=RIGHT, padx=(5, 0))
        self._button(
            actions,
            "Add to Playlist",
            self._queue_add_playlist,
            variant="warn",
        ).pack(side=RIGHT)

    def _build_search_tab(self) -> None:
        top = Frame(self.search_tab, bg=PANEL, pady=6)
        top.pack(fill=X)
        Label(
            top,
            text="Top clean song matches",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side=LEFT)
        self.recent_searches = ttk.Combobox(
            top,
            state="readonly",
            width=26,
            style="DjGoo.TCombobox",
        )
        self.recent_searches.pack(side=RIGHT)
        self.recent_searches.bind("<<ComboboxSelected>>", self._use_recent_search)
        body = Frame(self.search_tab, bg=PANEL)
        body.pack(fill=BOTH, expand=True)
        self.search_tree = self._tree(
            body,
            ("title", "artist", "duration", "source", "index"),
            ("Track", "Artist", "Time", "Source", ""),
            (220, 125, 55, 90, 0),
            selectmode="browse",
            hidden=("index",),
        )
        self.search_tree.bind(
            "<Double-1>",
            lambda _event: self._play_search_result("next"),
        )
        actions = Frame(self.search_tab, bg=PANEL, pady=7)
        actions.pack(fill=X)
        for label, timing in (
            ("Play Now", "now"),
            ("Add Next", "next"),
            ("Add Later", "later"),
        ):
            self._button(
                actions,
                label,
                lambda value=timing: self._play_search_result(value),
                variant={
                    "now": "danger",
                    "next": "primary",
                    "later": "neutral",
                }[timing],
            ).pack(side=LEFT, padx=(0, 5))

    def _build_history_tab(self) -> None:
        body = Frame(self.history_tab, bg=PANEL, pady=6)
        body.pack(fill=BOTH, expand=True)
        self.history_tree = self._tree(
            body,
            ("title", "artist", "played", "mode", "uri"),
            ("Track", "Artist", "Played", "Mode", ""),
            (235, 125, 90, 70, 0),
            selectmode="browse",
            hidden=("uri",),
        )
        actions = Frame(self.history_tab, bg=PANEL, pady=7)
        actions.pack(fill=X)
        self._button(
            actions,
            "Play Next",
            lambda: self._play_history("next"),
            variant="primary",
        ).pack(side=LEFT)
        self._button(
            actions,
            "Play Now",
            lambda: self._play_history("now"),
            variant="danger",
        ).pack(side=LEFT, padx=5)

    def _build_playlists_tab(self) -> None:
        top = Frame(self.playlists_tab, bg=PANEL, pady=6)
        top.pack(fill=X)
        create = Entry(
            top,
            textvariable=self.new_playlist_name,
            bg=ENTRY_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        create.pack(side=LEFT, fill=X, expand=True, ipady=5)
        create.bind("<Return>", lambda _event: self._create_playlist())
        self._button(
            top,
            "Create",
            self._create_playlist,
            variant="primary",
        ).pack(side=LEFT, padx=(5, 0))
        body = Frame(self.playlists_tab, bg=PANEL)
        body.pack(fill=BOTH, expand=True)
        self.playlist_list = Listbox(
            body,
            bg=PANEL_2,
            fg=TEXT,
            selectbackground="#1f5e5a",
            selectforeground=TEXT,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            width=18,
            exportselection=False,
            font=("Segoe UI", 9),
        )
        self.playlist_list.pack(side=LEFT, fill=Y, padx=(0, 6))
        self.playlist_list.bind("<<ListboxSelect>>", self._playlist_selected)
        track_frame = Frame(body, bg=PANEL)
        track_frame.pack(side=LEFT, fill=BOTH, expand=True)
        self.playlist_tree = self._tree(
            track_frame,
            ("title", "artist", "duration"),
            ("Track", "Artist", "Time"),
            (235, 125, 55),
            selectmode="browse",
        )
        actions = Frame(self.playlists_tab, bg=PANEL, pady=7)
        actions.pack(fill=X)
        self._button(
            actions,
            "Queue",
            lambda: self._playlist_action(False),
            variant="primary",
        ).pack(side=LEFT)
        self._button(
            actions,
            "Shuffle",
            lambda: self._playlist_action(True),
        ).pack(side=LEFT, padx=5)
        self._button(
            actions,
            "Add Current",
            self._add_current_to_playlist,
            variant="warn",
        ).pack(side=RIGHT)

    def toggle_drawer(self) -> None:
        self._drawer_open = not self._drawer_open
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self._drawer_open:
            self.compact.configure(width=COMPACT_WIDTH, height=EXPANDED_HEIGHT)
            self.drawer.pack(side=RIGHT, fill=BOTH, expand=True)
            self.root.geometry(
                f"{EXPANDED_WIDTH}x{EXPANDED_HEIGHT}+{x}+{y}"
            )
        else:
            self.drawer.pack_forget()
            self.compact.configure(width=COMPACT_WIDTH, height=COMPACT_HEIGHT)
            self.root.geometry(
                f"{COMPACT_WIDTH}x{COMPACT_HEIGHT}+{x}+{y}"
            )

    def send(
        self,
        intent: str,
        *,
        query: str = "",
        playlist: str = "",
        value: Any = 0,
        payload: dict[str, Any] | None = None,
        pending_key: str = "",
        status: str = "Sending to DjGoo...",
    ) -> str | None:
        key = pending_key or f"{intent}:{query}:{playlist}:{value}"
        if key in self._pending_keys:
            self._set_status("That action is already in progress.", WARN)
            return None
        item = mini_player_command(
            intent,
            query=query,
            playlist=playlist,
            value=value,
            payload=payload,
        )
        try:
            append_queue_item(self.queue_path, item)
        except OSError as exc:
            self._set_status(f"Could not send action: {exc}", DANGER)
            return None
        command_id = str(item["command_id"])
        self._pending[command_id] = {
            "sent_at": time.time(),
            "key": key,
            "intent": intent,
            "query": query,
            "playlist": playlist,
        }
        self._pending_keys.add(key)
        self._set_status(status, ACCENT)
        return command_id

    def play_request(self, timing: str, *, query: str | None = None) -> None:
        request = str(query if query is not None else self.request.get()).strip()
        if not request:
            self._set_status(
                "Type a song, artist, playlist URL, or station seed.",
                WARN,
            )
            return
        if query is None:
            self.request.set("")
        self._remember_search(request)
        intent = {"now": "play_now", "later": "queue_request"}.get(
            timing,
            "play",
        )
        label = {"now": "Playing now", "later": "Adding later"}.get(
            timing,
            "Adding next",
        )
        self.send(
            intent,
            query=request,
            pending_key=f"request:{timing}:{request.lower()}",
            status=f"{label}: {request}",
        )

    def _toggle_pause(self) -> None:
        intent = "resume" if bool(self._payload.get("paused")) else "pause"
        self.send(intent, pending_key="control:pause")

    def _schedule_search(self, event=None) -> None:
        if event is not None and event.keysym in {
            "Return",
            "Up",
            "Down",
            "Left",
            "Right",
            "Tab",
        }:
            return
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        query = self.request.get().strip()
        if len(query) < 2:
            return
        self._search_after = self.root.after(
            650,
            lambda: self._request_search(query),
        )

    def _request_search(self, query: str) -> None:
        self._search_after = None
        if "search" in self._pending_keys:
            self._queued_search_query = query
            return
        self.send(
            "mini_search",
            query=query,
            pending_key="search",
            status=f"Searching: {query}",
        )

    def _change_radio_mode(self, _event=None) -> None:
        mode = self.station_mode.get().strip().lower()
        self.send(
            "mini_radio_mode",
            value=mode,
            pending_key="radio:mode",
            status=f"Changing radio to {mode.title()}...",
        )

    def _set_volume(self, _event=None) -> None:
        target = round(float(self.volume_value.get()))
        self.send(
            "mini_set_volume",
            value=target,
            pending_key="control:set_volume",
            status=f"Setting volume to {target}...",
        )

    def _selected_queue_ids(self) -> list[str]:
        return [str(item_id) for item_id in self.queue_tree.selection()]

    def _queue_action(self, intent: str) -> None:
        selected = self._selected_queue_ids()
        if not selected:
            self._set_status("Select one or more queued tracks first.", WARN)
            return
        if intent in {"mini_queue_play_now", "mini_queue_move_next"}:
            selected = selected[:1]
        self.send(
            intent,
            payload={"track_ids": selected},
            pending_key=f"queue:{intent}",
        )

    def _queue_add_playlist(self) -> None:
        selected = self._selected_queue_ids()
        playlist = self.playlist_name.get().strip()
        if not selected or not playlist:
            self._set_status(
                "Select queued tracks and a playlist first.",
                WARN,
            )
            return
        self.send(
            "mini_playlist_add",
            playlist=playlist,
            payload={"track_ids": selected},
            pending_key="queue:add_playlist",
        )

    def _shuffle_requests(self) -> None:
        self.send(
            "mini_queue_shuffle_requests",
            pending_key="queue:shuffle",
        )

    def _clear_queue(self) -> None:
        self.send("mini_queue_clear", pending_key="queue:clear")

    def _queue_drag_start(self, event) -> None:
        self._drag_item = self.queue_tree.identify_row(event.y)
        self._drag_changed = False

    def _queue_drag_motion(self, event) -> None:
        target = self.queue_tree.identify_row(event.y)
        if not self._drag_item:
            return
        outside = (
            event.x < 0
            or event.y < 0
            or event.x >= self.queue_tree.winfo_width()
            or event.y >= self.queue_tree.winfo_height()
        )
        if outside:
            self._set_status("Release to remove this song from the queue.", DANGER)
            return
        if not target or target == self._drag_item:
            return
        self.queue_tree.move(self._drag_item, "", self.queue_tree.index(target))
        self._drag_changed = True

    def _queue_drag_end(self, event) -> None:
        outside = (
            event.x < 0
            or event.y < 0
            or event.x >= self.queue_tree.winfo_width()
            or event.y >= self.queue_tree.winfo_height()
        )
        if self._drag_item and outside:
            self.send(
                "mini_queue_remove_many",
                payload={"track_ids": [self._drag_item]},
                pending_key="queue:drag_remove",
                status="Removing song from the queue...",
            )
        elif self._drag_changed:
            self.send(
                "mini_queue_reorder",
                payload={"track_ids": list(self.queue_tree.get_children())},
                pending_key="queue:reorder",
                status="Saving the new queue order...",
            )
        self._drag_item = ""
        self._drag_changed = False

    def _play_search_result(self, timing: str) -> None:
        selected = self.search_tree.selection()
        if not selected:
            self._set_status("Select a search result first.", WARN)
            return
        values = self.search_tree.item(selected[0], "values")
        index = int(values[-1])
        if 0 <= index < len(self._search_results):
            self.play_request(
                timing,
                query=str(self._search_results[index].get("uri") or ""),
            )

    def _play_history(self, timing: str) -> None:
        selected = self.history_tree.selection()
        if not selected:
            self._set_status("Select a history track first.", WARN)
            return
        uri = str(self.history_tree.item(selected[0], "values")[-1])
        self.play_request(timing, query=uri)

    def _play_expanded_recent(self) -> None:
        selection = self.expanded_recent.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(self._expanded_history):
            self.play_request(
                "next",
                query=str(self._expanded_history[index].get("uri") or ""),
            )

    def _create_playlist(self) -> None:
        name = self.new_playlist_name.get().strip()
        if not name:
            self._set_status("Enter a short playlist name.", WARN)
            return
        self.send(
            "mini_playlist_create",
            playlist=name,
            pending_key=f"playlist:create:{name.lower()}",
            status=f"Creating {name}...",
        )

    def _selected_playlist_name(self) -> str:
        selection = self.playlist_list.curselection()
        if not selection:
            return ""
        return str(self.playlist_list.get(selection[0])).split("  (", 1)[0]

    def _playlist_selected(self, _event=None) -> None:
        name = self._selected_playlist_name()
        playlists = (
            self._payload.get("playlists")
            if isinstance(self._payload.get("playlists"), list)
            else []
        )
        selected = next(
            (item for item in playlists if str(item.get("name")) == name),
            None,
        )
        self.playlist_tree.delete(*self.playlist_tree.get_children())
        for index, track in enumerate((selected or {}).get("tracks", [])):
            self.playlist_tree.insert(
                "",
                END,
                iid=f"playlist-track-{index}",
                values=(
                    str(track.get("title") or "Unknown"),
                    str(track.get("artist") or ""),
                    format_time(int(track.get("duration_seconds") or 0)),
                ),
            )

    def _playlist_action(self, shuffle: bool) -> None:
        name = self._selected_playlist_name()
        if not name:
            self._set_status("Select a playlist first.", WARN)
            return
        self.send(
            "shuffle_playlist" if shuffle else "play_playlist",
            playlist=name,
            pending_key=f"playlist:play:{name}:{shuffle}",
        )

    def _add_current_to_playlist(self) -> None:
        name = self._selected_playlist_name()
        if not name or not isinstance(self._payload.get("current"), dict):
            self._set_status(
                "Select a playlist while a song is playing.",
                WARN,
            )
            return
        self.send(
            "mini_playlist_add_current",
            playlist=name,
            pending_key="playlist:add_current",
        )

    def _use_recent_search(self, _event=None) -> None:
        query = self.recent_searches.get().strip()
        if query:
            self.request.set(query)
            self._request_search(query)

    def _remember_search(self, query: str) -> None:
        recent = [
            str(value)
            for value in self.settings.get("recent_searches", [])
            if str(value).strip()
        ]
        recent = [value for value in recent if value.lower() != query.lower()]
        recent.insert(0, query)
        self.settings["recent_searches"] = recent[:12]
        self.recent_searches.configure(values=recent[:12])
        self._save_settings()

    def _poll(self) -> None:
        if self._closing:
            return
        self._poll_receipts()
        payload = self.state.latest()
        if isinstance(payload, dict):
            self._apply_state(payload)
        self.root.after(350, self._poll)

    def _poll_receipts(self) -> None:
        now = time.time()
        completed = []
        for command_id, pending in list(self._pending.items()):
            receipt = self.receipts.read(command_id, consume=True)
            if receipt is not None:
                completed.append(command_id)
                success = bool(receipt.get("success"))
                result = receipt.get("result")
                if isinstance(result, dict):
                    message = str(
                        result.get("message")
                        or result.get("status")
                        or "Completed"
                    )
                    if pending.get("intent") == "mini_search":
                        self._apply_search_results(result.get("results", []))
                    if str(pending.get("intent") or "").startswith(
                        "mini_playlist_"
                    ):
                        self._apply_playlist_result(
                            result,
                            pending=pending,
                            success=success,
                        )
                else:
                    message = str(result or "Completed")
                self._set_status(message, GOOD if success else DANGER)
            elif now - float(pending.get("sent_at") or now) > 25:
                completed.append(command_id)
                self._set_status(
                    "DjGoo did not acknowledge that action. Check the health lights.",
                    DANGER,
                )
        for command_id in completed:
            pending = self._pending.pop(command_id, {})
            self._pending_keys.discard(str(pending.get("key") or ""))
            if pending.get("intent") == "mini_search" and self._queued_search_query:
                query = self._queued_search_query
                self._queued_search_query = ""
                self._request_search(query)

    def _apply_playlist_result(
        self,
        result: dict[str, Any],
        *,
        pending: dict[str, Any],
        success: bool,
    ) -> None:
        if not success:
            return
        playlist = str(
            result.get("playlist") or pending.get("playlist") or ""
        ).strip()
        playlists = result.get("playlists")
        if playlist:
            self._preferred_playlist = playlist
            self.playlist_name.set(playlist)
        if isinstance(playlists, list):
            self._payload["playlists"] = playlists
            self._playlist_fingerprint = ""
            self._update_playlists(playlists)
        if pending.get("intent") == "mini_playlist_create":
            entered = self.new_playlist_name.get().strip()
            requested = str(pending.get("playlist") or "").strip()
            if entered.lower() == requested.lower():
                self.new_playlist_name.set("")

    def _apply_state(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        current = (
            payload.get("current")
            if isinstance(payload.get("current"), dict)
            else {}
        )
        title = str(
            current.get("title")
            or payload.get("title")
            or "DjGoo is waiting for music"
        )
        artist = str(current.get("artist") or payload.get("artist") or "")
        playback_state = str(payload.get("playback_state") or "idle").title()
        station = (
            payload.get("station_details")
            if isinstance(payload.get("station_details"), dict)
            else None
        )
        queue = payload.get("queue") if isinstance(payload.get("queue"), list) else []
        detail_parts = [playback_state]
        if artist:
            detail_parts.append(artist)
        if str(payload.get("mode")) == "REQUEST" and payload.get("requester"):
            detail_parts.append(f"Requested by {payload.get('requester')}")
        if station:
            detail_parts.append(str(station.get("name") or "Radio"))
            reason = str(station.get("reason") or "").strip()
            if reason:
                detail_parts.append(reason)
        self.title.set(title)
        self.detail.set("  |  ".join(detail_parts))
        self.pause_button.configure(
            text="Resume" if bool(payload.get("paused")) else "Pause"
        )
        self.queue_button.configure(text=f"Queue {len(queue)}")
        self._update_progress(payload)
        self._update_health(payload)
        self._update_artwork(
            str(current.get("artwork_url") or payload.get("artwork_url") or "")
        )
        self._update_radio(station)
        self._update_queue(queue)
        self._update_history(payload.get("history", []))
        self._update_playlists(payload.get("playlists", []))
        if not self.volume_scale.identify(
            self.volume_scale.winfo_pointerx() - self.volume_scale.winfo_rootx(),
            self.volume_scale.winfo_pointery() - self.volume_scale.winfo_rooty(),
        ):
            volume = int(payload.get("volume") or 0)
            self.volume_value.set(volume)
            self.volume_label.configure(text=str(volume))
        if station:
            self.expanded_station.set(
                f"{station.get('name', 'Radio')}  |  "
                f"{station.get('mode', 'balanced').title()}  |  "
                f"{station.get('reason', '')}"
            )
        else:
            self.expanded_station.set("No active station")
        next_track = queue[0] if queue else {}
        self.expanded_next.set(
            f"Next: {next_track.get('title', 'Nothing queued')}"
            + (
                f"  |  {next_track.get('artist')}"
                if next_track.get("artist")
                else ""
            )
        )

    def _update_progress(self, payload: dict[str, Any]) -> None:
        duration = int(payload.get("duration_seconds") or 0)
        position = int(payload.get("position_seconds") or 0)
        updated_at = float(payload.get("updated_at") or time.time())
        if (
            not payload.get("paused")
            and str(payload.get("playback_state")) == "playing"
        ):
            position += max(0, int(time.time() - updated_at))
        position = min(position, duration) if duration else position
        self.progress_text.set(
            f"{format_time(position)} / {format_time(duration)}"
        )
        self.progress_bar["value"] = (
            position / duration * 100 if duration else 0
        )

    def _update_health(self, payload: dict[str, Any]) -> None:
        health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
        stale_after = int(payload.get("stale_after_seconds") or 8)
        stale = time.time() - float(payload.get("updated_at") or 0) > stale_after
        self.health_canvas.delete("all")
        for index, key in enumerate(("discord", "music_core", "voice")):
            ready = bool((health.get(key) or {}).get("ready")) and not stale
            color = GOOD if ready else DANGER if health.get(key) else WARN
            self.health_canvas.create_oval(
                3 + index * 18,
                3,
                13 + index * 18,
                13,
                fill=color,
                outline="",
            )
        core_ready = (
            bool((health.get("discord") or {}).get("ready"))
            and bool((health.get("music_core") or {}).get("ready"))
            and not stale
        )
        self.expanded_health.set(
            "  |  ".join(
                f"{str((health.get(key) or {}).get('label') or key).replace('_', ' ').title()}: "
                f"{'Ready' if bool((health.get(key) or {}).get('ready')) and not stale else 'Offline'}"
                for key in ("discord", "music_core", "voice")
            )
        )
        for button in self._core_buttons:
            button.configure(
                state="normal" if core_ready else "disabled",
                bg=(
                    getattr(button, "_djgoo_normal_bg", PANEL_3)
                    if core_ready
                    else PANEL_2
                ),
            )
        if stale and not self._pending:
            self._set_status("DjGoo is reconnecting to the active session.", WARN)

    def _update_radio(self, station: dict[str, Any] | None) -> None:
        active = station is not None
        self.radio_summary.set(
            str(station.get("name") or "Radio") if station else "Radio off"
        )
        self.radio_label.configure(fg=GOOD if active else MUTED)
        if station:
            mode = str(station.get("mode") or "balanced").title()
            if self.station_mode.get() != mode:
                self.station_mode.set(mode)
        for control in self._radio_controls:
            with contextlib.suppress(Exception):
                control.configure(
                    state="normal" if active else "disabled",
                    **(
                        {
                            "bg": getattr(
                                control,
                                "_djgoo_normal_bg",
                                PANEL_3,
                            )
                            if active
                            else PANEL_2
                        }
                        if isinstance(control, Button)
                        else {}
                    ),
                )

    def _update_queue(self, queue: list[dict[str, Any]]) -> None:
        queue = [
            item
            if isinstance(item, dict)
            else {
                "id": f"legacy-{index}",
                "title": str(item),
                "duration_seconds": 0,
                "requester": "",
                "request_type": "automatic",
            }
            for index, item in enumerate(queue)
        ]
        fingerprint = json.dumps(queue, sort_keys=True, ensure_ascii=True)
        total = sum(int(item.get("duration_seconds") or 0) for item in queue)
        next_title = str((queue[0] if queue else {}).get("title") or "")
        self.queue_summary.set(
            f"{len(queue)} tracks  |  {format_time(total)}"
            + (f"  |  Next: {next_title}" if next_title else "")
        )
        if fingerprint == self._queue_fingerprint or self._drag_item:
            return
        self._queue_fingerprint = fingerprint
        selection = set(self.queue_tree.selection())
        self.queue_tree.delete(*self.queue_tree.get_children())
        for item in queue:
            track_id = str(item.get("id") or "")
            self.queue_tree.insert(
                "",
                END,
                iid=track_id,
                values=(
                    str(item.get("title") or "Unknown"),
                    format_time(int(item.get("duration_seconds") or 0)),
                    str(item.get("requester") or ""),
                    str(item.get("request_type") or "automatic").title(),
                ),
            )
            self._request_tree_artwork(
                self.queue_tree,
                track_id,
                str(item.get("artwork_url") or ""),
            )
        retained = [
            item_id for item_id in selection if self.queue_tree.exists(item_id)
        ]
        if retained:
            self.queue_tree.selection_set(retained)

    def _apply_search_results(self, results: Any) -> None:
        self._search_results = (
            [dict(item) for item in results if isinstance(item, dict)]
            if isinstance(results, list)
            else []
        )
        self.search_tree.delete(*self.search_tree.get_children())
        for index, item in enumerate(self._search_results):
            self.search_tree.insert(
                "",
                END,
                iid=f"search-{index}",
                values=(
                    str(item.get("title") or "Unknown"),
                    str(item.get("artist") or ""),
                    format_time(int(item.get("duration_seconds") or 0)),
                    str(item.get("source") or ""),
                    index,
                ),
            )
        if self._search_results:
            self.tabs.select(self.search_tab)

    def _update_history(self, history: Any) -> None:
        items = (
            [item for item in history if isinstance(item, dict)]
            if isinstance(history, list)
            else []
        )
        fingerprint = json.dumps(items, sort_keys=True, ensure_ascii=True)
        if fingerprint == self._history_fingerprint:
            return
        self._history_fingerprint = fingerprint
        self._expanded_history = items[:5]
        self.expanded_recent.delete(0, END)
        for item in self._expanded_history:
            artist = str(item.get("artist") or "")
            self.expanded_recent.insert(
                END,
                f"{item.get('title', 'Unknown')}"
                + (f"  -  {artist}" if artist else ""),
            )
        self.history_tree.delete(*self.history_tree.get_children())
        for index, item in enumerate(items):
            played_at = float(item.get("played_at") or 0)
            played = (
                time.strftime("%I:%M %p", time.localtime(played_at))
                if played_at
                else ""
            )
            self.history_tree.insert(
                "",
                END,
                iid=f"history-{index}",
                values=(
                    str(item.get("title") or "Unknown"),
                    str(item.get("artist") or ""),
                    played,
                    str(item.get("mode") or "").title(),
                    str(item.get("uri") or ""),
                ),
            )

    def _update_playlists(self, playlists: Any) -> None:
        items = (
            [item for item in playlists if isinstance(item, dict)]
            if isinstance(playlists, list)
            else []
        )
        fingerprint = json.dumps(items, sort_keys=True, ensure_ascii=True)
        if fingerprint == self._playlist_fingerprint:
            return
        self._playlist_fingerprint = fingerprint
        current = self._preferred_playlist or self._selected_playlist_name()
        self._preferred_playlist = ""
        names = [str(item.get("name") or "") for item in items]
        self.queue_playlist_combo.configure(values=names)
        if names and self.playlist_name.get() not in names:
            self.playlist_name.set(names[0])
        self.playlist_list.delete(0, END)
        for item in items:
            self.playlist_list.insert(
                END,
                f"{item.get('name', '')}  ({int(item.get('track_count') or 0)})",
            )
        if current in names:
            self.playlist_list.selection_set(names.index(current))
        elif names:
            self.playlist_list.selection_set(0)
        self._playlist_selected()

    def _request_tree_artwork(
        self,
        tree: ttk.Treeview,
        item_id: str,
        url: str,
    ) -> None:
        if not url or Image is None:
            return
        cache_key = f"{item_id}:{url}"
        cached = self._tree_artwork.get(cache_key)
        if cached is not None:
            with contextlib.suppress(Exception):
                tree.item(item_id, image=cached)
            return
        if cache_key in self._tree_artwork_loading:
            return
        self._tree_artwork_loading.add(cache_key)

        def load() -> None:
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "DjGoo/0.3"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    raw = response.read(2_000_000)
                image = Image.open(io.BytesIO(raw)).convert("RGB")
                side = min(image.size)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side)).resize(
                    (28, 28)
                )
                self.root.after(
                    0,
                    lambda: self._show_tree_artwork(
                        tree,
                        item_id,
                        cache_key,
                        image,
                    ),
                )
            except Exception:
                self._tree_artwork_loading.discard(cache_key)

        threading.Thread(
            target=load,
            name="DjGooQueueArtwork",
            daemon=True,
        ).start()

    def _show_tree_artwork(
        self,
        tree: ttk.Treeview,
        item_id: str,
        cache_key: str,
        image,
    ) -> None:
        self._tree_artwork_loading.discard(cache_key)
        if self._closing or ImageTk is None:
            return
        photo = ImageTk.PhotoImage(image)
        self._tree_artwork[cache_key] = photo
        with contextlib.suppress(Exception):
            if tree.exists(item_id):
                tree.item(item_id, image=photo)

    def _update_artwork(self, url: str) -> None:
        if not url or url == self._last_artwork_url or Image is None:
            return
        self._last_artwork_url = url

        def load() -> None:
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "DjGoo/0.3"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    raw = response.read(2_000_000)
                image = Image.open(io.BytesIO(raw)).convert("RGB")
                side = min(image.size)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop(
                    (left, top, left + side, top + side)
                ).resize((58, 58))
                self.root.after(0, lambda: self._show_artwork(image, url))
            except Exception:
                return

        threading.Thread(
            target=load,
            name="DjGooArtwork",
            daemon=True,
        ).start()

    def _show_artwork(self, image, url: str) -> None:
        if self._closing or url != self._last_artwork_url or ImageTk is None:
            return
        self._artwork_photo = ImageTk.PhotoImage(image)
        self.artwork.configure(image=self._artwork_photo, text="", width=58)

    def _set_status(self, message: str, color: str) -> None:
        self.status.set(str(message)[:110])
        self.status_label.configure(fg=color)
        self.status_canvas.itemconfigure(self.status_dot, fill=color)

    def _set_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.always_on_top.get()))
        self.settings["always_on_top"] = bool(self.always_on_top.get())
        self._save_settings()

    def _restore_position(self) -> None:
        self.recent_searches.configure(
            values=self.settings.get("recent_searches", [])
        )
        try:
            x = int(self.settings.get("x"))
            y = int(self.settings.get("y"))
        except (TypeError, ValueError):
            return
        self.root.geometry(f"{COMPACT_WIDTH}x{COMPACT_HEIGHT}+{x}+{y}")

    def _remember_position(self, _event=None) -> None:
        if (
            self._closing
            or time.monotonic() - self._last_position_save < 0.75
        ):
            return
        self._last_position_save = time.monotonic()
        self.settings["x"] = int(self.root.winfo_x())
        self.settings["y"] = int(self.root.winfo_y())
        self._save_settings()

    def _save_settings(self) -> None:
        with contextlib.suppress(OSError):
            self.settings_store.write(self.settings)

    def _close(self) -> None:
        self._closing = True
        self.settings["x"] = int(self.root.winfo_x())
        self.settings["y"] = int(self.root.winfo_y())
        self._save_settings()
        self.root.destroy()


def main() -> int:
    project_root = application_root()
    instance = SingleMiniPlayer(project_root / "data" / "mini-player.lock")
    if not instance.acquire():
        return 0
    try:
        root = Tk()
        DjGooMiniPlayer(root, project_root)
        root.mainloop()
    finally:
        instance.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
