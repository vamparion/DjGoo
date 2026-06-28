from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def read_json_file(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, dict) else fallback


def read_recent_log_lines(path: Path, *, limit: int = 80) -> List[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def build_state_snapshot(project_root: Path) -> Dict[str, Any]:
    playlists_data = read_json_file(project_root / "data" / "djgoo-playlists.json", {"playlists": {}})
    stations_data = read_json_file(project_root / "data" / "djgoo-stations.json", {"active": {}, "stations": {}})
    playlists = _playlist_summaries(playlists_data)
    stations = _station_summaries(stations_data)
    active_station = _active_station(stations_data)
    last_track = active_station.get("last_track") if active_station else None
    last_title = last_track.get("title", "") if isinstance(last_track, dict) else ""
    return {
        "playback": {
            "title": last_title,
            "artist": "",
            "station": active_station["name"] if active_station else "",
            "source": "Station memory" if last_title else "",
            "remaining": "",
            "queue_count": 0,
        },
        "queue": [],
        "playlists": playlists,
        "stations": stations,
        "active_station": active_station,
        "health": build_health(project_root),
        "logs": {
            "redbot": read_recent_log_lines(
                project_root / "data" / "discordbot" / "core" / "logs" / "latest.log",
                limit=20,
            ),
            "voice": read_recent_log_lines(project_root / "logs" / "voice-listener.log", limit=20),
        },
    }


def build_health(project_root: Path) -> Dict[str, Any]:
    return {
        "redbot": _process_status("redbot.exe", "redbot.exe"),
        "lavalink": _process_status("java.exe", "Lavalink.jar"),
        "voice": _process_status("python.exe", "voice.djgoo_voice_listener"),
        "nuclear": {"status": "unknown", "detail": "Checked by search endpoint"},
        "webhook": {"status": "configured" if (project_root / "config" / "secrets.json").exists() else "missing"},
    }


def _playlist_summaries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    playlists = data.get("playlists", {})
    if not isinstance(playlists, dict):
        return []
    result = []
    for name, playlist in sorted(playlists.items()):
        tracks = playlist.get("tracks", []) if isinstance(playlist, dict) else []
        result.append(
            {
                "name": str(name),
                "track_count": len([track for track in tracks if isinstance(track, dict)]),
                "tracks": tracks,
            }
        )
    return result


def _station_summaries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    stations = data.get("stations", {})
    if not isinstance(stations, dict):
        return []
    result = []
    for station in stations.values():
        if not isinstance(station, dict):
            continue
        result.append(
            {
                "id": station.get("id", ""),
                "name": station.get("name", ""),
                "seed": station.get("seed", ""),
                "liked_count": len(station.get("liked", [])),
                "more_like_count": len(station.get("more_like", [])),
                "less_like_count": len(station.get("less_like", [])),
                "banned_count": len(station.get("banned", [])),
                "skipped_count": len(station.get("skipped", [])),
                "last_track": station.get("last_track"),
                "liked": station.get("liked", []),
                "more_like": station.get("more_like", []),
                "less_like": station.get("less_like", []),
                "banned": station.get("banned", []),
                "skipped": station.get("skipped", []),
            }
        )
    return sorted(result, key=lambda item: str(item.get("name", "")).lower())


def _active_station(data: Dict[str, Any]) -> Dict[str, Any] | None:
    active = data.get("active", {})
    stations = data.get("stations", {})
    if not isinstance(active, dict) or not isinstance(stations, dict) or not active:
        return None
    station_id = next(iter(active.values()))
    station = stations.get(station_id)
    return station if isinstance(station, dict) else None


def _process_status(process_name: str, command_marker: str) -> Dict[str, str]:
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{$_.Name -eq '{process_name}' -and $_.CommandLine -like '*{command_marker}*'}} | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        output = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", script], text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return {"status": "unknown"}
    pid = output.strip()
    return {"status": "online", "pid": pid} if pid else {"status": "offline"}
