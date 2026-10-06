from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from voice.gaming_session import GamingSessionStore
from voice.sqlite_stations import SqliteDjGooStations
from voice.mini_player_protocol import MiniPlayerHistory
from voice.pairing_store import PairingStore


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
    measured_at = time.time()
    now_playing = read_json_file(
        project_root / "data" / "djgoo-now-playing.json",
        {},
    )
    now_playing, active_guild_id = _active_playback(now_playing)
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
    current = _hydrate_track_metadata(project_root, current)
    playback_state = str(now_playing.get("playback_state") or "idle")
    position_ms = int(now_playing.get("position_ms") or 0)
    if not position_ms:
        position_ms = int(float(now_playing.get("position_seconds") or 0) * 1000)
    sampled_at = float(now_playing.get("started_at") or measured_at)
    if playback_state == "playing":
        position_ms += max(0, int((measured_at - sampled_at) * 1000))
    live_queue = now_playing.get("queue") if isinstance(now_playing.get("queue"), list) else []
    gaming = GamingSessionStore(project_root / "data" / "djgoo-gaming-session.json")
    history = _hydrate_history_metadata(
        project_root,
        MiniPlayerHistory(project_root / "data" / "djgoo-mini-history.json").entries(),
    )
    players = _paired_players(project_root, active_guild_id)
    return {
        "playback": {
            "track_id": str(current.get("id") or ""),
            "title": str(current.get("title") or last_title),
            "artist": str(current.get("artist") or ""),
            "artwork_url": str(current.get("artwork_url") or ""),
            "station": str((now_playing.get("station_details") or {}).get("name") or (active_station["name"] if active_station else "")),
            "source": str(now_playing.get("mode") or ("Station memory" if last_title else "")),
            "remaining": str(now_playing.get("progress_text") or ""),
            "queue_count": len(live_queue),
            "requester": str(now_playing.get("requester") or ""),
            "state": playback_state,
            "position_ms": position_ms,
            "duration_ms": int(current.get("duration_seconds") or 0) * 1000,
            "playing": playback_state == "playing",
            "measured_at": measured_at,
            "volume": int(now_playing.get("volume") or 0),
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
        "players": players,
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


def _hydrate_history_metadata(
    project_root: Path,
    entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    cache = project_root / "cache" / "localtracks"
    metadata = read_json_file(cache / "metadata.json", {})
    streams = read_json_file(cache / "streams.json", {})
    hints = read_json_file(cache / "source-hints.json", {})
    by_source = {
        str(value.get("source_uri") or key): value
        for document in (metadata, streams, hints)
        for key, value in document.items()
        if isinstance(value, dict) and str(value.get("source_uri") or key).startswith(("https://", "http://"))
    }
    metadata = {**metadata, **{source: value for source, value in by_source.items()}}
    if not metadata:
        return entries
    hydrated: List[Dict[str, Any]] = []
    for entry in entries:
        hydrated.append(_hydrate_track_metadata(project_root, entry, metadata=metadata))
    return hydrated


def _hydrate_track_metadata(
    project_root: Path,
    track: Dict[str, Any],
    *,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    item = dict(track)
    metadata = metadata if metadata is not None else read_json_file(
        project_root / "cache" / "localtracks" / "metadata.json",
        {},
    )
    uri = str(item.get("uri") or "").replace("\\", "/")
    cached = metadata.get(uri) or metadata.get(uri.rsplit("/", 1)[-1])
    if not isinstance(cached, dict):
        return item
    source_uri = str(cached.get("source_uri") or "").strip()
    if source_uri.startswith(("https://", "http://")):
        item["uri"] = source_uri
        item["source_uri"] = source_uri
    elif "localtracks" in uri.casefold():
        item.pop("uri", None)
    artist = str(item.get("artist") or "").strip()
    if not artist or artist.casefold() == "unknown artist":
        item["artist"] = str(cached.get("artist") or artist)
    title = str(item.get("title") or "").strip()
    if not title or title.casefold() in {"unknown title", "unknown track"}:
        item["title"] = str(cached.get("title") or title)
    if not item.get("artwork_url") and cached.get("artwork_url"):
        item["artwork_url"] = cached["artwork_url"]
    if not item.get("duration_seconds") and cached.get("duration_seconds"):
        item["duration_seconds"] = cached["duration_seconds"]
    return item


def build_remote_state_snapshot(project_root: Path, *, privileged: bool = False) -> Dict[str, Any]:
    """Return the immediately useful state that fits Discord's inline relay."""
    full = build_state_snapshot(project_root)
    gaming = dict(full.get("gaming") or {})
    gaming["profiles"] = list(gaming.get("profiles") or []) if privileged else []
    playlists = [
        {
            "name": item.get("name"),
            "track_count": item.get("track_count", 0),
            "description": item.get("description", ""),
            "artwork_url": item.get("artwork_url", ""),
            "folder": item.get("folder", ""),
            "tags": item.get("tags", []),
            "smart_query": item.get("smart_query", ""),
            "tracks": [],
        }
        for item in list(full.get("playlists") or [])[:50]
        if isinstance(item, dict)
    ]
    state = {
        "protocol": 3,
        "generated_at": time.time(),
        "playback": full.get("playback") or {},
        "queue": list(full.get("queue") or [])[:12],
        "playlists": playlists,
        "stations": [],
        "active_station": None,
        "health": full.get("health") or {},
        "health_summary": full.get("health_summary") or {},
        "gaming": gaming,
        "players": list(full.get("players") or []) if privileged else [],
        "logs": {},
        "timeline": list(full.get("timeline") or [])[:4] if privileged else [],
        "history": list(full.get("history") or [])[:50],
        "capabilities": {
        "system_management": False,
        "diagnostics": privileged,
        "library_management": privileged,
        "settings_management": privileged,
        },
    }
    active = full.get("active_station")
    if isinstance(active, dict):
        station = {
            key: active.get(key)
            for key in (
                "id", "name", "seed", "seed_type", "liked_count",
                "more_like_count", "less_like_count", "banned_count",
                "skipped_count", "familiar_percent", "balanced_percent",
                "discovery_percent", "artist_spacing", "song_spacing",
                "last_selection_reason", "last_drift_score", "last_track",
            )
        }
        station.update({key: [] for key in ("liked", "more_like", "less_like", "banned", "skipped", "played", "recent", "feedback_history", "snapshots", "seed_examples")})
        state["active_station"] = station
        state["stations"] = [station]
    _remove_private_track_sources(state)
    return state


def _active_playback(document: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    guilds = document.get("guilds") if isinstance(document, dict) else None
    if not isinstance(guilds, dict) or not guilds:
        return document, 0
    candidates = [(str(key), value) for key, value in guilds.items() if isinstance(value, dict)]
    if not candidates:
        return {}, 0
    guild_id, state = max(candidates, key=lambda item: float(item[1].get("saved_at") or 0))
    return state, int(guild_id) if guild_id.isdigit() else 0


def _paired_players(project_root: Path, guild_id: int) -> List[Dict[str, Any]]:
    database = project_root / "data" / "djgoo-pairing.db"
    if not database.exists() or not guild_id:
        return []
    try:
        store = PairingStore(database, project_root / "data" / "djgoo-pairing-secret.bin")
        devices = store.list_guild_devices(guild_id)
    except (OSError, ValueError):
        return []
    now = time.time()
    players: Dict[int, Dict[str, Any]] = {}
    for device in devices:
        player = players.setdefault(device.user_id, {
            "id": str(device.user_id), "discord_user_id": str(device.user_id),
            "username": device.display_name or f"Discord user {device.user_id}",
            "role": device.role, "device_name": device.device_name,
            "device_type": device.device_type, "last_seen": device.last_seen_at,
            "online": False, "device_count": 0,
        })
        player["device_count"] += 1
        player["online"] = bool(player["online"] or now - device.last_seen_at <= 90)
        if device.last_seen_at >= float(player["last_seen"]):
            player.update({"last_seen": device.last_seen_at, "device_name": device.device_name})
        if device.display_name:
            player["username"] = device.display_name
        if device.role in {"host", "moderator"}:
            player["role"] = device.role
    return sorted(players.values(), key=lambda item: float(item["last_seen"]), reverse=True)


def _remove_private_track_sources(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("uri", None)
        for child in value.values():
            _remove_private_track_sources(child)
    elif isinstance(value, list):
        for child in value:
            _remove_private_track_sources(child)


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
    health_root = Path(os.environ.get("DJGOO_HEALTH_DIR") or project_root / "data" / "health")
    heartbeat = read_json_file(health_root / f"{component}.json", {})
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
    if os.environ.get("DJGOO_NATIVE_HOST") == "1":
        red = _heartbeat_status(project_root, "redbot", max_age_seconds=120.0) or {
            "status": "starting", "detail": "Music heartbeat is pending", "source": "heartbeat"
        }
        try:
            with socket.create_connection(("::1", 2333), timeout=0.35):
                lavalink = {"status": "online", "detail": "Audio Engine is accepting connections", "source": "socket"}
        except OSError:
            lavalink = {"status": "starting", "detail": "Audio Engine is starting", "source": "socket"}
        voice = _heartbeat_status(project_root, "voice", max_age_seconds=90.0) or {
            "status": "online", "detail": "Optional speech runtime is not active", "source": "optional"
        }
        return {
            "redbot": red,
            "lavalink": lavalink,
            "voice": voice,
            "web": {"status": "online", "detail": "Web remote is serving this request", "source": "service"},
        }
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
    if os.environ.get("DJGOO_NATIVE_HOST") == "1":
        return {"status": "unknown", "detail": "Native Host owns component state", "source": "native-host"}
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
