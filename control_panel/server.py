from __future__ import annotations

import argparse
import json
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from control_panel.actions import enqueue_panel_command, run_project_script
from control_panel.models import error, ok
from control_panel.state import build_state_snapshot
from voice.nuclear_resolver import NuclearResolver
from voice.gaming_session import GamingSessionStore
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
        if parsed.path == "/api/search":
            query = _query_param(parsed.query, "q")
            if not query.strip():
                return 400, error("Missing search query")
            resolved = NuclearResolver().resolve_track_query(query)
            return 200, ok({"query": query, "result": resolved})
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
            if path == "/api/profile/role":
                return 200, ok({"profile": gaming.set_role(0, str(payload.get("profile_id") or ""), str(payload.get("role") or "member"), actor_role=actor_role)})
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
