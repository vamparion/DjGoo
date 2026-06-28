from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from voice.command_queue import append_queue_item


ACTION_TO_INTENT = {
    "play": "play",
    "play_next": "play",
    "start_radio": "start_radio",
    "stop_radio": "stop_radio",
    "skip": "skip",
    "toggle_pause": "pause",
    "pause": "pause",
    "resume": "resume",
    "stop": "stop",
    "replay": "replay",
    "queue": "queue",
    "like": "station_like_current",
    "more_like": "station_more_like_current",
    "less_like": "station_less_like_current",
    "ban": "station_ban_current",
    "save_current": "save_current_to_playlist",
    "save_last": "save_last_to_playlist",
    "play_playlist": "play_playlist",
    "shuffle_playlist": "shuffle_playlist",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
}


def queue_path_for_project(project_root: Path) -> Path:
    return project_root / "data" / "voice-command-queue.jsonl"


def resolve_panel_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    if action not in ACTION_TO_INTENT:
        raise ValueError(f"Unknown panel action: {action}")
    return {
        "type": "command",
        "source": "panel",
        "created_at": time.time(),
        "intent": ACTION_TO_INTENT[action],
        "query": str(payload.get("query", "")).strip(),
        "playlist": str(payload.get("playlist", "")).strip(),
        "value": int(payload.get("value", 0) or 0),
        "confidence": 1.0,
        "raw": f"panel:{action}",
    }


def enqueue_panel_command(project_root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    item = resolve_panel_action(payload)
    append_queue_item(queue_path_for_project(project_root), item)
    return item


def run_project_script(project_root: Path, script_name: str) -> Dict[str, Any]:
    allowed = {"Reset-DjGoo.command.ps1", "Start-DjGoo.command.ps1", "Start-DjGoo-Voice.command.ps1", "stop-djgoo.ps1"}
    if script_name not in allowed:
        raise ValueError(f"Script is not allowed: {script_name}")
    script = project_root / script_name
    if not script.exists():
        raise FileNotFoundError(str(script))
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(project_root),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {"script": script_name, "started": True}
