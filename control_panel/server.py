from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import subprocess
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from control_panel.actions import enqueue_panel_command, run_project_script
from control_panel.models import error, ok
from control_panel.state import build_state_snapshot
from voice.nuclear_resolver import NuclearResolver
from voice.gaming_session import GamingSessionStore
from voice.djgoo_playlists import DjGooPlaylists
from voice.sqlite_stations import SqliteDjGooStations
from voice.mini_player_protocol import MiniPlayerHistory
from voice.pairing_store import PairingStore
from voice.tls_identity import ensure_tls_identity


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_handler_class(project_root: Path, static_root: Path | None = None):
    resolved_static_root = static_root or project_root / "control_panel_dist"

    class Handler(ControlPanelHandler):
        root = project_root
        static_root = resolved_static_root

    return Handler


class ControlPanelHandler(BaseHTTPRequestHandler):
    root: Path = PROJECT_ROOT
    static_root: Path = PROJECT_ROOT / "control_panel_dist"

    @classmethod
    def route_get(cls, path: str) -> Tuple[int, Dict[str, Any]]:
        parsed = urlparse(path)
        if parsed.path == "/api/healthz":
            return 200, ok({"service": "djgoo-control-panel"})
        if parsed.path == "/api/state":
            return 200, ok({"state": build_state_snapshot(cls.root)})
        if parsed.path == "/api/audio-inputs":
            python = cls.root / ".voice-venv" / "Scripts" / "python.exe"
            helper = cls.root / "tools" / "list_audio_inputs.py"
            result = subprocess.run([str(python), str(helper)], cwd=cls.root, capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                return 503, error((result.stderr or "Voice input scan failed")[-500:], status=503)
            return 200, ok(json.loads(result.stdout))
        if parsed.path == "/api/search":
            query = _query_param(parsed.query, "q")
            if not query.strip():
                return 400, error("Missing search query")
            resolved = NuclearResolver().resolve_track_query(query)
            return 200, ok({"query": query, "result": resolved})
        if parsed.path == "/api/backup":
            snapshot = build_state_snapshot(cls.root)
            return 200, ok({"backup": {key: snapshot.get(key) for key in ("playlists", "stations", "gaming", "timeline")}})
        if parsed.path == "/api/library/search":
            query = _query_param(parsed.query, "q").casefold().strip()
            state = build_state_snapshot(cls.root)
            matches = []
            for playlist in state.get("playlists", []):
                for track in playlist.get("tracks", []):
                    if query in f"{track.get('title', '')} {track.get('artist', '')} {playlist.get('name', '')}".casefold():
                        matches.append({"kind": "playlist", "group": playlist.get("name"), **track})
            for station in state.get("stations", []):
                for bucket in ("liked", "more_like", "less_like", "banned", "played"):
                    for track in station.get(bucket, []):
                        if query in f"{track.get('title', '')} {track.get('artist', '')} {station.get('name', '')}".casefold():
                            matches.append({"kind": bucket, "group": station.get("name"), **track})
            return 200, ok({"results": matches[:100]})
        return 404, error("Not found", status=404)

    @classmethod
    def route_post(cls, path: str, payload: Dict[str, Any], *, is_local: bool = False) -> Tuple[int, Dict[str, Any]]:
        try:
            gaming = GamingSessionStore(cls.root / "data" / "djgoo-gaming-session.json")
            if path == "/api/profile":
                existing_hosts = [item for item in gaming.profiles(0) if item.get("role") == "host"]
                role = "host" if is_local and not existing_hosts else "member"
                profile = gaming.create_profile(
                    str(payload.get("username") or ""),
                    role=role,
                    device_id=str(payload.get("device_id") or ""),
                )
                return 200, ok({"profile": profile})
            profile = gaming.profile(str(payload.get("token") or ""))
            actor_role = str((profile or {}).get("role") or ("host" if is_local else "guest"))
            if path == "/api/settings":
                return 200, ok({"settings": gaming.update_settings(0, payload.get("settings") or {}, actor_role=actor_role)})
            if path == "/api/audio-input":
                if not is_local or actor_role != "host":
                    raise PermissionError("Only the local DjGoo host can change the microphone")
                name = str(payload.get("name") or "").strip()
                if not name:
                    raise ValueError("Choose an available microphone")
                secrets_path = cls.root / "config" / "secrets.json"
                secrets = json.loads(secrets_path.read_text(encoding="utf-8-sig"))
                voice = secrets.setdefault("voice", {})
                voice["input_device"] = name
                temporary = secrets_path.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(secrets, indent=2) + "\n", encoding="utf-8")
                os.replace(temporary, secrets_path)
                from tools.djgoo_stack import control_request
                recovery = control_request("reset", timeout=2.0)
                return 200, ok({"input_device": name, "recovery": recovery})
            if path == "/api/profile/role":
                return 200, ok({"profile": gaming.set_role(0, str(payload.get("profile_id") or ""), str(payload.get("role") or "member"), actor_role=actor_role)})
            if path == "/api/player/revoke":
                if not is_local or actor_role != "host":
                    raise PermissionError("Only the local DjGoo host can revoke a player")
                user_id = int(str(payload.get("discord_user_id") or "0"))
                guild_id = int(str(payload.get("guild_id") or "1513011181202309290"))
                pairing = PairingStore(cls.root / "data" / "djgoo-pairing.db", cls.root / "data" / "djgoo-pairing-secret.bin")
                return 200, ok({"revoked": pairing.revoke_web_devices(user_id, guild_id)})
            if path == "/api/command":
                command = dict(payload)
                command.update(
                    {
                        "profile_id": str((profile or {}).get("id") or ""),
                        "username": str((profile or {}).get("username") or "Guest"),
                        "actor_role": actor_role,
                    }
                )
                return 200, ok({"item": enqueue_panel_command(cls.root, command)})
            if path.startswith("/api/station/"):
                if actor_role not in {"host", "moderator"}:
                    raise PermissionError("A DjGoo moderator is required")
                seed = str(payload.get("seed") or "")
                stations = SqliteDjGooStations(cls.root / "data" / "djgoo-stations.sqlite3", legacy_json_path=cls.root / "data" / "djgoo-stations.json")
                action = path.rsplit("/", 1)[-1]
                if action == "settings": result = stations.update_settings(seed, payload.get("settings") or {})
                elif action == "undo": result = stations.undo_feedback(seed, str(payload.get("feedback") or ""))
                elif action == "snapshot": result = stations.create_snapshot(seed, str(payload.get("name") or ""))
                elif action == "restore": result = stations.restore_snapshot(seed, str(payload.get("snapshot_id") or ""))
                elif action == "clone": result = stations.clone(seed, str(payload.get("new_seed") or ""))
                elif action == "merge": result = stations.merge([str(value) for value in payload.get("seeds", [])], str(payload.get("new_seed") or ""))
                else: return 404, error("Unknown station action", status=404)
                return 200, ok({"result": result})
            if path.startswith("/api/playlist/"):
                if actor_role not in {"host", "moderator"}:
                    raise PermissionError("A DjGoo moderator is required")
                name = str(payload.get("playlist") or "")
                playlists = DjGooPlaylists(cls.root / "data" / "djgoo-playlists.json")
                action = path.rsplit("/", 1)[-1]
                if action == "metadata": result = playlists.update_metadata(name, payload.get("metadata") or {})
                elif action == "reorder": result = {"name": playlists.reorder_tracks(name, [str(value) for value in payload.get("track_ids", [])])}
                elif action == "cleanup": result = playlists.cleanup(name)
                elif action == "replace": result = {"name": playlists.replace_track(name, str(payload.get("track_id") or ""), payload.get("replacement") or {})}
                elif action == "remove": result = dict(zip(("name", "removed"), playlists.remove_tracks(name, [str(value) for value in payload.get("track_ids", [])])))
                elif action == "import":
                    reviewed = [item for item in payload.get("tracks", []) if isinstance(item, dict)]
                    results = [playlists.add_track(name, item) for item in reviewed]
                    result = {"name": name, "added": sum(int(item.added) for item in results), "duplicates": sum(int(not item.added) for item in results)}
                elif action == "from-history":
                    seconds = max(60, int(payload.get("seconds") or 3600)); cutoff = time.time() - seconds
                    history = MiniPlayerHistory(cls.root / "data" / "djgoo-mini-history.json").entries()
                    results = [playlists.add_track(name, item) for item in reversed(history) if float(item.get("played_at") or 0) >= cutoff]
                    result = {"name": name, "added": sum(int(item.added) for item in results), "duplicates": sum(int(not item.added) for item in results)}
                else: return 404, error("Unknown playlist action", status=404)
                return 200, ok({"result": result})
            if path == "/api/system/reset":
                return 200, ok(run_project_script(cls.root, "Reset-DjGoo.command.ps1"))
            if path == "/api/system/start-voice":
                return 200, ok(run_project_script(cls.root, "Start-DjGoo-Voice.command.ps1"))
            if path == "/api/system/stop":
                return 200, ok(run_project_script(cls.root, "stop-djgoo.ps1"))
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            return 400, error(str(exc))
        return 404, error("Not found", status=404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            status, body = self.route_get(self.path)
            self._send_json(status, body)
            return
        self._send_static(parsed.path)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, error("Invalid JSON"))
            return
        is_local = self.client_address[0] in {"127.0.0.1", "::1"}
        status, body = self.route_post(
            urlparse(self.path).path,
            payload if isinstance(payload, dict) else {},
            is_local=is_local,
        )
        self._send_json(status, body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, request_path: str) -> None:
        relative = request_path.strip("/") or "index.html"
        target = (self.static_root / relative).resolve()
        static_root = self.static_root.resolve()
        if not str(target).startswith(str(static_root)) or not target.exists():
            target = static_root / "index.html"
        if not target.exists():
            self._send_json(404, error("DjGoo's mobile controls are not installed.", status=404))
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        if target.name == "service-worker.js":
            self.send_header("Service-Worker-Allowed", "/")
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


def _query_param(query: str, name: str) -> str:
    values = parse_qs(query).get(name, [])
    if not values:
        return ""
    return unquote(values[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--tls", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    handler = create_handler_class(root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    scheme = "http"
    if args.tls:
        addresses = tuple(
            sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(socket.gethostname(), None)
                    if item[0] in {socket.AF_INET, socket.AF_INET6}
                }
            )
        )
        identity = ensure_tls_identity(
            root / "data" / "control-panel.crt",
            root / "data" / "control-panel.key",
            additional_ip_addresses=addresses,
        )
        server.socket = identity.server_context().wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"DjGoo control panel running at {scheme}://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
