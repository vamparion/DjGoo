# DjGoo Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the DjGoo local admin web control panel: low-click live controls, Nuclear search, station/playlists management, health, and reset controls.

**Architecture:** Add a local Python HTTP API under `control_panel/` that reads existing DjGoo data files and appends commands to the existing voice-command queue. Add a React + Vite frontend under `control-panel-ui/` that implements the approved low-click mockup and talks to that API. Keep guest mode out of Phase 1 except for a visible disabled preview and backend-ready boundaries.

**Tech Stack:** Python standard library HTTP server for the local API, existing `voice.*` modules for playlists/stations/Nuclear/command queue, React + Vite + TypeScript for the UI, PowerShell startup script for Windows.

---

## Scope

This plan implements the local admin panel only.

Included:

- Local API server.
- Local frontend.
- Live-state snapshot from project files/logs where possible.
- Command enqueueing for Redbot bridge.
- Nuclear search endpoint.
- Playlist and station read/write endpoints.
- Health endpoint.
- Reset/start/stop command endpoints.
- Windows startup script.

Excluded:

- Public hosting.
- Discord login.
- Guest phone mode write access.
- Replacing Redbot playback.
- Full real-time websocket updates.

## File Structure

Create:

- `control_panel/__init__.py`: package marker.
- `control_panel/models.py`: JSON response helpers and dataclasses.
- `control_panel/state.py`: reads playlists, stations, queue path, logs, and process health.
- `control_panel/actions.py`: converts panel actions into existing DjGoo command queue items and safe PowerShell process actions.
- `control_panel/server.py`: local HTTP API and static file serving.
- `control_panel_ui/package.json`: Vite project metadata.
- `control_panel_ui/index.html`: frontend mount point.
- `control_panel_ui/src/main.tsx`: React entrypoint.
- `control_panel_ui/src/App.tsx`: app composition and state orchestration.
- `control_panel_ui/src/api.ts`: typed API client.
- `control_panel_ui/src/types.ts`: shared frontend types.
- `control_panel_ui/src/styles.css`: low-click visual design.
- `control_panel_ui/src/components/CommandBar.tsx`: top command bar.
- `control_panel_ui/src/components/LivePanel.tsx`: now-playing and one-click controls.
- `control_panel_ui/src/components/SmartActions.tsx`: smart action tiles.
- `control_panel_ui/src/components/QueuePanel.tsx`: queue display.
- `control_panel_ui/src/components/StationPanel.tsx`: station memory display/actions.
- `control_panel_ui/src/components/PlaylistPanel.tsx`: playlist management.
- `control_panel_ui/src/components/HealthPanel.tsx`: system status.
- `control_panel_ui/src/components/PersistentFooter.tsx`: bottom critical controls.
- `Start-DjGoo-ControlPanel.ps1`: launches the API server.
- `tests/test_control_panel_state.py`: backend state tests.
- `tests/test_control_panel_actions.py`: backend action tests.
- `tests/test_control_panel_server.py`: API tests.

Modify:

- `.gitignore`: ignore frontend `node_modules`, `dist`, and control panel runtime logs if needed.
- `README.md`: add control panel start instructions.

## Task 1: Backend State Snapshot

**Files:**

- Create: `control_panel/__init__.py`
- Create: `control_panel/models.py`
- Create: `control_panel/state.py`
- Test: `tests/test_control_panel_state.py`

- [ ] **Step 1: Write failing tests for state snapshot**

Create `tests/test_control_panel_state.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from control_panel.state import build_state_snapshot, read_recent_log_lines


class ControlPanelStateTests(unittest.TestCase):
    def test_build_state_snapshot_reads_playlists_stations_and_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "logs").mkdir()
            (root / "data" / "djgoo-playlists.json").write_text(
                json.dumps({"playlists": {"chill": {"tracks": [{"title": "Song", "uri": "u:song"}]}}}),
                encoding="utf-8",
            )
            (root / "data" / "djgoo-stations.json").write_text(
                json.dumps(
                    {
                        "active": {"123": "80s"},
                        "stations": {
                            "80s": {
                                "id": "80s",
                                "name": "80S radio",
                                "seed": "80s",
                                "liked": [{"title": "Like", "uri": "u:like"}],
                                "more_like": [],
                                "less_like": [],
                                "banned": [],
                                "skipped": [],
                                "recent": [],
                                "played": [],
                                "last_track": {"title": "Last", "uri": "u:last"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "logs" / "voice-listener.log").write_text("voice ready\n", encoding="utf-8")

            snapshot = build_state_snapshot(root)

        self.assertEqual(snapshot["playlists"][0]["name"], "chill")
        self.assertEqual(snapshot["stations"][0]["name"], "80S radio")
        self.assertEqual(snapshot["active_station"]["name"], "80S radio")
        self.assertIn("redbot", snapshot["health"])
        self.assertEqual(snapshot["logs"]["voice"][-1], "voice ready")

    def test_read_recent_log_lines_returns_tail_without_error_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.log"

            self.assertEqual(read_recent_log_lines(missing, limit=5), [])

    def test_read_recent_log_lines_limits_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.log"
            path.write_text("a\nb\nc\n", encoding="utf-8")

            self.assertEqual(read_recent_log_lines(path, limit=2), ["b", "c"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_state
```

Expected: fail with `ModuleNotFoundError: No module named 'control_panel'`.

- [ ] **Step 3: Implement state snapshot**

Create `control_panel/__init__.py`:

```python
"""Local DjGoo web control panel backend."""
```

Create `control_panel/models.py`:

```python
from __future__ import annotations

from typing import Any, Dict


def ok(data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return payload


def error(message: str, *, status: int = 400) -> Dict[str, Any]:
    return {"ok": False, "error": message, "status": status}
```

Create `control_panel/state.py`:

```python
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
    return {
        "playback": {
            "title": "",
            "artist": "",
            "station": active_station["name"] if active_station else "",
            "source": "",
            "remaining": "",
            "queue_count": 0,
        },
        "queue": [],
        "playlists": playlists,
        "stations": stations,
        "active_station": active_station,
        "health": build_health(project_root),
        "logs": {
            "redbot": read_recent_log_lines(project_root / "data" / "discordbot" / "core" / "logs" / "latest.log", limit=20),
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
        result.append({"name": str(name), "track_count": len([t for t in tracks if isinstance(t, dict)]), "tracks": tracks})
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
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_state
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add control_panel tests/test_control_panel_state.py
git commit -m "feat: add control panel state snapshot"
```

## Task 2: Backend Actions And Command Queue

**Files:**

- Create: `control_panel/actions.py`
- Test: `tests/test_control_panel_actions.py`

- [ ] **Step 1: Write failing action tests**

Create `tests/test_control_panel_actions.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from control_panel.actions import enqueue_panel_command, queue_path_for_project, resolve_panel_action


class ControlPanelActionTests(unittest.TestCase):
    def test_resolve_panel_action_maps_play_next_to_play_command(self):
        item = resolve_panel_action({"action": "play_next", "query": "Sandstorm"})

        self.assertEqual(item["intent"], "play")
        self.assertEqual(item["query"], "Sandstorm")
        self.assertEqual(item["source"], "panel")

    def test_resolve_panel_action_maps_radio(self):
        item = resolve_panel_action({"action": "start_radio", "query": "80s"})

        self.assertEqual(item["intent"], "start_radio")
        self.assertEqual(item["query"], "80s")

    def test_resolve_panel_action_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            resolve_panel_action({"action": "explode"})

    def test_enqueue_panel_command_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = enqueue_panel_command(root, {"action": "skip"})
            queue_path = queue_path_for_project(root)
            lines = queue_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(item["intent"], "skip")
        self.assertEqual(json.loads(lines[0])["intent"], "skip")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_actions
```

Expected: fail with `ModuleNotFoundError` or missing `control_panel.actions`.

- [ ] **Step 3: Implement action mapping**

Create `control_panel/actions.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_actions
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add control_panel/actions.py tests/test_control_panel_actions.py
git commit -m "feat: add control panel command actions"
```

## Task 3: Local HTTP API

**Files:**

- Create: `control_panel/server.py`
- Test: `tests/test_control_panel_server.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_control_panel_server.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from control_panel.server import ControlPanelHandler, create_handler_class


class FakeRequest:
    def makefile(self, *args, **kwargs):
        raise RuntimeError("not used")


class ControlPanelServerTests(unittest.TestCase):
    def test_route_state_returns_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_get("/api/state")

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("state", body)

    def test_route_command_rejects_bad_json_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_post("/api/command", {"action": "bad"})

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_route_command_accepts_skip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handler_cls = create_handler_class(root)

            status, body = handler_cls.route_post("/api/command", {"action": "skip"})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["intent"], "skip")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_server
```

Expected: fail with missing `control_panel.server`.

- [ ] **Step 3: Implement server routes**

Create `control_panel/server.py`:

```python
from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import unquote, urlparse

from control_panel.actions import enqueue_panel_command, run_project_script
from control_panel.models import error, ok
from control_panel.state import build_state_snapshot
from voice.nuclear_resolver import NuclearResolver


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_handler_class(project_root: Path, static_root: Path | None = None):
    static_root = static_root or project_root / "control_panel_ui" / "dist"

    class Handler(ControlPanelHandler):
        root = project_root
        static_root = static_root

    return Handler


class ControlPanelHandler(BaseHTTPRequestHandler):
    root: Path = PROJECT_ROOT
    static_root: Path = PROJECT_ROOT / "control_panel_ui" / "dist"

    @classmethod
    def route_get(cls, path: str) -> Tuple[int, Dict[str, Any]]:
        if path == "/api/state":
            return 200, ok({"state": build_state_snapshot(cls.root)})
        if path.startswith("/api/search"):
            parsed = urlparse(path)
            query = ""
            for part in parsed.query.split("&"):
                if part.startswith("q="):
                    query = unquote(part[2:].replace("+", " "))
            if not query.strip():
                return 400, error("Missing search query")
            resolved = NuclearResolver().resolve_track_query(query)
            return 200, ok({"query": query, "result": resolved})
        return 404, error("Not found", status=404)

    @classmethod
    def route_post(cls, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            if path == "/api/command":
                return 200, ok({"item": enqueue_panel_command(cls.root, payload)})
            if path == "/api/system/reset":
                return 200, ok(run_project_script(cls.root, "Reset-DjGoo.command.ps1"))
            if path == "/api/system/start-voice":
                return 200, ok(run_project_script(cls.root, "Start-DjGoo-Voice.command.ps1"))
            if path == "/api/system/stop":
                return 200, ok(run_project_script(cls.root, "stop-djgoo.ps1"))
        except (ValueError, FileNotFoundError) as exc:
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
        status, body = self.route_post(urlparse(self.path).path, payload if isinstance(payload, dict) else {})
        self._send_json(status, body)

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
        if not str(target).startswith(str(self.static_root.resolve())) or not target.exists():
            target = self.static_root / "index.html"
        if not target.exists():
            self._send_json(404, error("Frontend is not built. Run npm run build in control_panel_ui.", status=404))
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    handler = create_handler_class(root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"DjGoo control panel running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run API tests and fix class variable issue if needed**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_control_panel_server
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add control_panel/server.py tests/test_control_panel_server.py
git commit -m "feat: add control panel local API"
```

## Task 4: Frontend Scaffold And API Client

**Files:**

- Create: `control_panel_ui/package.json`
- Create: `control_panel_ui/index.html`
- Create: `control_panel_ui/src/main.tsx`
- Create: `control_panel_ui/src/types.ts`
- Create: `control_panel_ui/src/api.ts`
- Create: `control_panel_ui/src/App.tsx`
- Create: `control_panel_ui/src/styles.css`
- Modify: `.gitignore`

- [ ] **Step 1: Create Vite project files**

Create `control_panel_ui/package.json`:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5174",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1 --port 5174"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "typescript": "latest",
    "react": "latest",
    "react-dom": "latest",
    "lucide-react": "latest"
  },
  "devDependencies": {}
}
```

Create `control_panel_ui/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>DjGoo Control</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `control_panel_ui/src/types.ts`:

```ts
export type Track = {
  title: string;
  uri?: string;
};

export type Playlist = {
  name: string;
  track_count: number;
  tracks: Track[];
};

export type Station = {
  id: string;
  name: string;
  seed: string;
  liked_count: number;
  more_like_count: number;
  less_like_count: number;
  banned_count: number;
  skipped_count: number;
  last_track?: Track | null;
  liked: Track[];
  more_like: Track[];
  less_like: Track[];
  banned: Track[];
  skipped: Track[];
};

export type HealthItem = {
  status: string;
  pid?: string;
  detail?: string;
};

export type ControlState = {
  playback: {
    title: string;
    artist: string;
    station: string;
    source: string;
    remaining: string;
    queue_count: number;
  };
  queue: Track[];
  playlists: Playlist[];
  stations: Station[];
  active_station: Station | null;
  health: Record<string, HealthItem>;
  logs: Record<string, string[]>;
};
```

Create `control_panel_ui/src/api.ts`:

```ts
import type { ControlState } from "./types";

const API_BASE = import.meta.env.VITE_DJGOO_API_BASE || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data as T;
}

export async function getState(): Promise<ControlState> {
  const data = await request<{ ok: true; state: ControlState }>("/api/state");
  return data.state;
}

export async function sendCommand(action: string, payload: Record<string, unknown> = {}) {
  return request<{ ok: true; item: unknown }>("/api/command", {
    method: "POST",
    body: JSON.stringify({ action, ...payload }),
  });
}

export async function searchNuclear(query: string) {
  return request<{ ok: true; query: string; result: string | null }>(`/api/search?q=${encodeURIComponent(query)}`);
}

export async function resetDjGoo() {
  return request<{ ok: true }>("/api/system/reset", { method: "POST", body: "{}" });
}
```

Create `control_panel_ui/src/main.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create a temporary `control_panel_ui/src/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getState } from "./api";
import type { ControlState } from "./types";

export function App() {
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getState().then(setState).catch((err) => setError(String(err.message || err)));
  }, []);

  return (
    <main className="appShell">
      <h1>DjGoo Control</h1>
      {error && <p className="error">{error}</p>}
      <pre>{JSON.stringify(state, null, 2)}</pre>
    </main>
  );
}
```

Create temporary `control_panel_ui/src/styles.css`:

```css
body {
  margin: 0;
  background: #0d1014;
  color: #f4f7fb;
  font-family: Inter, Segoe UI, system-ui, sans-serif;
}

.appShell {
  padding: 24px;
}

.error {
  color: #ff7482;
}
```

Modify `.gitignore`:

```gitignore
control_panel_ui/node_modules/
control_panel_ui/dist/
```

- [ ] **Step 2: Install frontend dependencies**

Run:

```powershell
cd control_panel_ui
npm install
```

Expected: `node_modules` and `package-lock.json` are created.

- [ ] **Step 3: Build frontend**

Run:

```powershell
cd control_panel_ui
npm run build
```

Expected: Vite build succeeds and creates `dist`.

- [ ] **Step 4: Commit**

```powershell
git add .gitignore control_panel_ui/package.json control_panel_ui/package-lock.json control_panel_ui/index.html control_panel_ui/src
git commit -m "feat: scaffold control panel frontend"
```

## Task 5: Low-Click React UI

**Files:**

- Modify: `control_panel_ui/src/App.tsx`
- Modify: `control_panel_ui/src/styles.css`
- Create component files listed in File Structure.

- [ ] **Step 1: Create component files**

Create `CommandBar.tsx`, `LivePanel.tsx`, `SmartActions.tsx`, `QueuePanel.tsx`, `StationPanel.tsx`, `PlaylistPanel.tsx`, `HealthPanel.tsx`, and `PersistentFooter.tsx` using the approved mockup structure.

Use this component API:

```tsx
import type { ControlState } from "../types";

export type CommandSender = (action: string, payload?: Record<string, unknown>) => Promise<void>;

export type PanelProps = {
  state: ControlState;
  send: CommandSender;
};
```

For action buttons, call:

```tsx
void send("skip");
void send("like");
void send("less_like");
void send("ban");
void send("stop_radio");
void send("save_current", { playlist: "chill" });
```

- [ ] **Step 2: Replace App with polling and action handling**

`App.tsx` must:

- Fetch `/api/state` on load.
- Poll every 3 seconds.
- Show errors in a top banner.
- Send commands through `sendCommand`.
- Optimistically show a “sent” status.

Use this skeleton:

```tsx
import { useEffect, useState } from "react";
import { getState, resetDjGoo, sendCommand } from "./api";
import { CommandBar } from "./components/CommandBar";
import { HealthPanel } from "./components/HealthPanel";
import { LivePanel } from "./components/LivePanel";
import { PersistentFooter } from "./components/PersistentFooter";
import { PlaylistPanel } from "./components/PlaylistPanel";
import { QueuePanel } from "./components/QueuePanel";
import { SmartActions } from "./components/SmartActions";
import { StationPanel } from "./components/StationPanel";
import type { ControlState } from "./types";

export function App() {
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");

  async function refresh() {
    try {
      setState(await getState());
      setError("");
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, []);

  async function send(action: string, payload: Record<string, unknown> = {}) {
    setStatus(`Sending ${action}`);
    try {
      if (action === "reset") {
        await resetDjGoo();
      } else {
        await sendCommand(action, payload);
      }
      setStatus(`Sent ${action}`);
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  if (!state) {
    return <main className="loading">Loading DjGoo...</main>;
  }

  return (
    <div className="app">
      <CommandBar send={send} />
      {error && <div className="banner error">{error}</div>}
      <main className="content">
        <nav className="rail">
          <button className="active">Live</button>
          <button>Find</button>
          <button>Radio</button>
          <button>Lists</button>
          <button>Guests</button>
          <button>Logs</button>
        </nav>
        <section className="stack">
          <LivePanel state={state} send={send} />
          <SmartActions state={state} send={send} />
          <div className="split">
            <QueuePanel state={state} send={send} />
            <StationPanel state={state} send={send} />
          </div>
        </section>
        <aside className="side">
          <HealthPanel state={state} send={send} />
          <PlaylistPanel state={state} send={send} />
          <section className="panel">
            <h2>Guest Mode Later</h2>
            <p>Phone request controls will live here after local admin tools are stable.</p>
          </section>
        </aside>
      </main>
      <PersistentFooter state={state} send={send} status={status} />
    </div>
  );
}
```

- [ ] **Step 3: Port approved low-click CSS**

Port the CSS from `docs/mockups/djgoo-control-panel-low-clicks.html` into `control_panel_ui/src/styles.css`, removing static-only classes that are not used.

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd control_panel_ui
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add control_panel_ui/src
git commit -m "feat: build low-click control panel UI"
```

## Task 6: Startup Script And README

**Files:**

- Create: `Start-DjGoo-ControlPanel.ps1`
- Modify: `README.md`

- [ ] **Step 1: Create startup script**

Create `Start-DjGoo-ControlPanel.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "control-panel.log"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (!(Test-Path $python)) {
    throw "Bot dependencies are not installed. Missing $python"
}

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe") -and
    ($_.ProcessId -ne $PID) -and
    ($_.CommandLine -like "*control_panel.server*")
}

if ($alreadyRunning) {
    "DjGoo control panel is already running. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    Start-Process "http://127.0.0.1:8765"
    exit 0
}

Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "control_panel.server", "--project-root", $ProjectRoot, "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError (Join-Path $logDir "control-panel.err.log") `
    -WindowStyle Hidden

Start-Sleep -Seconds 1
Start-Process "http://127.0.0.1:8765"
"Started DjGoo control panel. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
```

- [ ] **Step 2: Add README instructions**

Add this section to `README.md`:

```markdown
## Control Panel

Build the web UI once after frontend changes:

```powershell
cd control_panel_ui
npm install
npm run build
cd ..
```

Start the local control panel:

```powershell
.\Start-DjGoo-ControlPanel.ps1
```

Open:

```text
http://127.0.0.1:8765
```

The panel is local/admin-only in Phase 1. Guest phone mode comes later.
```

- [ ] **Step 3: Run API server smoke check**

Run:

```powershell
$p = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","control_panel.server","--project-root",(Get-Location),"--port","8765" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
Invoke-RestMethod http://127.0.0.1:8765/api/state
Stop-Process -Id $p.Id -Force
```

Expected: JSON object with `ok: true` and a `state` property.

- [ ] **Step 4: Commit**

```powershell
git add Start-DjGoo-ControlPanel.ps1 README.md
git commit -m "docs: add control panel startup"
```

## Task 7: Final Verification

**Files:**

- No new files unless fixing verification failures.

- [ ] **Step 1: Run all Python tests**

Run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.voice-venv\Scripts\python.exe -m unittest discover -s tests
```

Expected:

- `.venv`: all tests pass.
- `.voice-venv`: tests pass with Redbot-dependent skips.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
cd control_panel_ui
npm run build
cd ..
```

Expected: Vite build succeeds.

- [ ] **Step 3: Start server and inspect UI**

Run:

```powershell
.\Start-DjGoo-ControlPanel.ps1
```

Open:

```text
http://127.0.0.1:8765
```

Verify:

- The live screen loads.
- Critical controls remain visible.
- Search/command bar is at the top.
- Health cards show Redbot/Lavalink/Voice/Nuclear status.
- The UI is usable at a phone-width browser viewport.

- [ ] **Step 4: Commit final fixes**

If verification required fixes:

```powershell
git add <fixed files>
git commit -m "fix: polish control panel verification"
```

If no fixes were required, do not create an empty commit.

## Self-Review

Spec coverage:

- Low-click live controls: Task 5.
- Nuclear search: Tasks 3 and 5.
- Stations: Tasks 1, 2, and 5.
- Playlists: Tasks 1, 2, and 5.
- Health/logs: Tasks 1, 3, and 5.
- Reset controls: Tasks 2, 3, 5, and 6.
- Guest mode: visible Phase 1 preview only; full implementation deferred as planned.

Placeholder scan:

- No placeholder markers or unspecified implementation steps are intentionally left.

Type consistency:

- Backend action names match frontend calls: `skip`, `like`, `more_like`, `less_like`, `ban`, `stop_radio`, `save_current`, `reset`.
- API routes match frontend client: `/api/state`, `/api/command`, `/api/search`, `/api/system/reset`.
