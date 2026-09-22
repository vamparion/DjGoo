from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from voice.gaming_session import GamingSessionStore
from voice.sqlite_stations import SqliteDjGooStations
from voice.mini_player_protocol import MiniPlayerHistory


CORE_COMPONENTS = ("redbot", "lavalink", "voice", "web")


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
    now_playing = read_json_file(
        project_root / "data" / "djgoo-now-playing.json",
        {},
    )
    playlists_data = read_json_file(
        project_root / "data" / "djgoo-playlists.json",
        {"playlists": {}},
    )
    playlists = _playlist_summaries(playlists_data)
    station_db = project_root / "data" / "djgoo-stations.sqlite3"
    if station_db.exists():
        station_store = SqliteDjGooStations(station_db, legacy_json_path=project_root / "data" / "djgoo-stations.json")
        station_values = station_store.all_stations()
        stations = _station_summaries({"stations": {str(item.get("id")): item for item in station_values}})
        active_station = next((station_store.get_active(guild_id) for guild_id in station_store.active_guild_ids()), None)
    else:
        stations_data = read_json_file(project_root / "data" / "djgoo-stations.json", {"active": {}, "stations": {}})
        stations = _station_summaries(stations_data)
        active_station = _active_station(stations_data)
    last_track = active_station.get("last_track") if active_station else None
    last_title = last_track.get("title", "") if isinstance(last_track, dict) else ""
    health = build_health(project_root)
    failed = [
        name
        for name in CORE_COMPONENTS
        if str((health.get(name) or {}).get("status") or "") != "online"
    ]
    current = now_playing.get("current") if isinstance(now_playing.get("current"), dict) else {}
    live_queue = now_playing.get("queue") if isinstance(now_playing.get("queue"), list) else []
    gaming = GamingSessionStore(project_root / "data" / "djgoo-gaming-session.json")
    history = MiniPlayerHistory(project_root / "data" / "djgoo-mini-history.json").entries()
    return {
        "playback": {
            "title": str(current.get("title") or last_title),
            "artist": str(current.get("artist") or ""),
            "station": str((now_playing.get("station_details") or {}).get("name") or (active_station["name"] if active_station else "")),
            "source": str(now_playing.get("mode") or ("Station memory" if last_title else "")),
            "remaining": str(now_playing.get("progress_text") or ""),
            "queue_count": len(live_queue),
            "requester": str(now_playing.get("requester") or ""),
            "state": str(now_playing.get("playback_state") or "idle"),
        },
        "queue": live_queue,
        "playlists": playlists,
        "stations": stations,
        "active_station": active_station,
        "health": health,
        "health_summary": {
            "ok": not failed,
            "failed_components": failed,
            "message": (
                "DjGoo is healthy"
                if not failed
                else "Failed components: " + ", ".join(failed)
            ),
        },
        "gaming": gaming.public_state(0),
        "logs": {
            "startup": read_recent_log_lines(
                project_root / "logs" / "startup.log",
                limit=30,
            ),
            "supervisor": read_recent_log_lines(
                project_root / "logs" / "components" / "supervisor.err.log",
                limit=30,
            ),
            "redbot": read_recent_log_lines(
                project_root / "logs" / "components" / "redbot.err.log",
                limit=30,
            )
            or read_recent_log_lines(
                project_root / "data" / "discordbot" / "core" / "logs" / "latest.log",
                limit=30,
            ),
            "voice": read_recent_log_lines(
                project_root / "logs" / "components" / "voice.err.log",
                limit=30,
            )
            or read_recent_log_lines(
                project_root / "logs" / "voice-listener.log",
                limit=30,
            ),
        },
        "timeline": _diagnostic_timeline(project_root),
        "history": history,
    }


def build_remote_state_snapshot(project_root: Path) -> Dict[str, Any]:
    """Return the deliberately narrow state exposed to paired web devices."""
    state = build_state_snapshot(project_root)
    playback = state.get("playback") if isinstance(state.get("playback"), dict) else {}
    queue = state.get("queue") if isinstance(state.get("queue"), list) else []
    return {
        "protocol": 1,
        "generated_at": time.time(),
        "playback": {
            key: playback.get(key)
            for key in ("title", "artist", "station", "remaining", "queue_count", "requester", "state")
        },
        "queue": [
            {
                key: item.get(key)
                for key in ("id", "title", "artist", "requester", "request_type", "duration")
            }
            for item in queue[:200]
            if isinstance(item, dict)
        ],
        "capabilities": {
            "system_management": False,
            "diagnostics": False,
            "secrets": False,
        },
    }


def _diagnostic_timeline(project_root: Path) -> List[Dict[str, str]]:
    events = read_recent_log_lines(project_root / "logs" / "djgoo-events.jsonl", limit=120)
    result: List[Dict[str, str]] = []
    labels = {
        "playback.lifecycle": "Playback changed",
        "gaming.vote": "Player vote recorded",
        "radio.recommendation.ranked": "Radio selected a track",
        "radio.recommendation.ranked_empty": "Radio could not find a clean match",
        "request.native_discord.detected": "Discord request accepted",
        "request.native_discord.limit_rejected": "Player request limit reached",
    }
    for line in reversed(events):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = str(item.get("event") or "")
        if event not in labels:
            continue
        detail = str(item.get("reason") or item.get("message") or item.get("station") or "")
        result.append({"time": str(item.get("ts") or ""), "title": labels[event], "detail": detail})
        if len(result) >= 30:
            break
    return result


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _supervisor_component_status(
    project_root: Path,
    component: str,
) -> Dict[str, Any] | None:
    supervisor = read_json_file(
        project_root / "data" / "djgoo-supervisor-state.json",
        {},
    )
    components = supervisor.get("components")
    if not isinstance(components, dict):
        return None
    item = components.get(component)
    if not isinstance(item, dict):
        return None

    pid = _integer(item.get("pid"))
    running = bool(item.get("running"))
    ready = bool(item.get("ready"))
    last_error = str(supervisor.get("last_error") or "").strip()
    if ready and running:
        return {
            "status": "online",
            "pid": str(pid) if pid else "",
            "detail": "Supervisor reports ready",
            "source": "supervisor",
        }
    if running:
        return {
            "status": "starting",
            "pid": str(pid) if pid else "",
            "detail": last_error or "Process is running but has not become ready",
            "source": "supervisor",
        }
    return {
        "status": "offline",
        "pid": str(pid) if pid else "",
        "detail": last_error or "Supervisor reports the component is stopped",
        "source": "supervisor",
    }


def _heartbeat_status(
    project_root: Path,
    component: str,
    *,
    max_age_seconds: float,
) -> Dict[str, Any] | None:
    heartbeat = read_json_file(
        project_root / "data" / "health" / f"{component}.json",
        {},
    )
    if not heartbeat:
        return None
    try:
        age = time.time() - float(heartbeat.get("timestamp") or 0)
    except (TypeError, ValueError):
        return None
    pid = _integer(heartbeat.get("pid"))
    if heartbeat.get("ready") is True and -5.0 <= age <= max_age_seconds:
        return {
            "status": "online",
            "pid": str(pid) if pid else "",
            "detail": f"Heartbeat is {max(0.0, age):.1f} seconds old",
            "source": "heartbeat",
        }
    return None


def _component_status(
    project_root: Path,
    component: str,
    *,
    process_name: str,
    command_marker: str,
    heartbeat_max_age: float,
) -> Dict[str, Any]:
    supervisor = _supervisor_component_status(project_root, component)
    if supervisor and supervisor.get("status") in {"online", "starting"}:
        return supervisor

    heartbeat = _heartbeat_status(
        project_root,
        component,
        max_age_seconds=heartbeat_max_age,
    )
    if heartbeat:
        return heartbeat

    process = _process_status(process_name, command_marker)
    if process.get("status") == "online":
        process["detail"] = "Matching portable process found; readiness heartbeat is pending"
        process["source"] = "process"
        return process
    return supervisor or process


def build_health(project_root: Path) -> Dict[str, Any]:
    return {
        "redbot": _component_status(
            project_root,
            "redbot",
            process_name="python.exe",
            command_marker="start_redbot_selector.py",
            heartbeat_max_age=120.0,
        ),
        "lavalink": _component_status(
            project_root,
            "lavalink",
            process_name="java.exe",
            command_marker="Lavalink.jar",
            heartbeat_max_age=45.0,
        ),
        "voice": _component_status(
            project_root,
            "voice",
            process_name="python.exe",
            command_marker="voice.djgoo_voice_listener",
            heartbeat_max_age=45.0,
        ),
        "web": _component_status(
            project_root,
            "web",
            process_name="python.exe",
            command_marker="control_panel.server",
            heartbeat_max_age=120.0,
        ),
        "nuclear": {
            "status": "unknown",
            "detail": "Checked by search endpoint",
        },
        "webhook": {
            "status": (
                "configured"
                if (project_root / "config" / "secrets.json").exists()
                else "missing"
            )
        },
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
                "track_count": len(
                    [track for track in tracks if isinstance(track, dict)]
                ),
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
                "played": station.get("played", []),
                "recent": station.get("recent", []),
                "feedback_history": station.get("feedback_history", []),
                "snapshots": station.get("snapshots", []),
                "familiar_percent": station.get("familiar_percent", 55),
                "discovery_percent": station.get("discovery_percent", 20),
                "balanced_percent": max(0, 100 - int(station.get("familiar_percent", 55)) - int(station.get("discovery_percent", 20))),
                "artist_spacing": station.get("artist_spacing", 4),
                "song_spacing": station.get("song_spacing", 50),
                "seed_type": station.get("seed_type", "auto"),
                "seed_examples": station.get("seed_examples", []),
                "last_selection_reason": station.get("last_selection_reason", ""),
                "last_drift_score": station.get("last_drift_score", 0),
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


def _process_status(process_name: str, command_marker: str) -> Dict[str, Any]:
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{$_.Name -eq '{process_name}' -and $_.CommandLine -like '*{command_marker}*'}} | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        output = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command", script],
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "status": "unknown",
            "detail": "Windows process query failed",
            "source": "process",
        }
    pid = output.strip()
    if pid:
        return {"status": "online", "pid": pid, "source": "process"}
    return {
        "status": "offline",
        "detail": f"No {process_name} process matched {command_marker}",
        "source": "process",
    }
