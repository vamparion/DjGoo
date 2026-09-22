from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
COMPONENT_LOG_DIR = LOG_DIR / "components"
PID_DIR = PROJECT_ROOT / "data" / "pids"
HEALTH_DIR = PROJECT_ROOT / "data" / "health"
STATE_PATH = PROJECT_ROOT / "data" / "djgoo-supervisor-state.json"
LOCK_PATH = PROJECT_ROOT / "data" / "djgoo-supervisor.lock"
SUPERVISOR_PID_PATH = PID_DIR / "supervisor.json"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = int(os.environ.get("DJGOO_CONTROL_PORT", "49177"))

JAVA = Path(
    os.environ.get(
        "DJGOO_JAVA",
        r"C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot\bin\java.exe",
    )
)
BOT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
VOICE_PYTHON = PROJECT_ROOT / ".voice-venv" / "Scripts" / "python.exe"
PYTHONW = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
REDBOT_SELECTOR = PROJECT_ROOT / "tools" / "start_redbot_selector.py"
LAVALINK_DIR = PROJECT_ROOT / "data" / "discordbot" / "cogs" / "Audio"
LAVALINK_JAR = LAVALINK_DIR / "Lavalink.jar"
EVENT_LOG = LOG_DIR / "djgoo-events.jsonl"

WINDOWS_DETACHED_FLAGS = 0
if os.name == "nt":
    WINDOWS_DETACHED_FLAGS = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )


class Logger:
    def __init__(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOG_DIR / "startup.log"
        self._lock = threading.Lock()

    def event(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")


LOG = Logger()


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    command: list[str]
    cwd: Path
    command_markers: tuple[str, ...]
    ready: Callable[[], bool]
    ready_timeout: float


class SingleInstance:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.handle.close()
            self.handle = None
            return False
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


def installed_version_text() -> str:
    try:
        payload = json.loads(
            (PROJECT_ROOT / "data" / "installed-version.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return "development"
    if not isinstance(payload, dict):
        return "development"
    return str(payload.get("version") or "development").strip() or "development"


class SupervisorState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.desired_running = False
        self.reset_requested = False
        self.shutdown_requested = False
        self.last_error = ""
        self.started_at = time.time()
        self.version = installed_version_text()
        self.component_status: dict[str, dict[str, Any]] = {}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "supervisor_pid": os.getpid(),
                "desired_running": self.desired_running,
                "reset_requested": self.reset_requested,
                "shutdown_requested": self.shutdown_requested,
                "last_error": self.last_error,
                "started_at": self.started_at,
                "supervisor_version": self.version,
                "components": self.component_status,
            }


STATE = SupervisorState()


def atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def pid_path(name: str) -> Path:
    return PID_DIR / f"{name}.json"


def health_path(name: str) -> Path:
    return HEALTH_DIR / f"{name}.json"


def process_record_matches(record: dict[str, Any] | None, spec: ComponentSpec) -> bool:
    if not record:
        return False
    try:
        pid = int(record.get("pid") or 0)
        recorded_create_time = float(record.get("create_time") or 0)
        proc = psutil.Process(pid)
        actual_create_time = float(proc.create_time())
        cmdline = " ".join(proc.cmdline()).lower()
    except (psutil.Error, OSError, TypeError, ValueError):
        return False
    if recorded_create_time and abs(actual_create_time - recorded_create_time) > 1.0:
        return False
    return all(marker.lower() in cmdline for marker in spec.command_markers)


def component_record(name: str) -> dict[str, Any] | None:
    return read_json(pid_path(name))


def component_running(spec: ComponentSpec) -> bool:
    return process_record_matches(component_record(spec.name), spec)


def heartbeat_ready(
    name: str,
    *,
    max_age_seconds: float,
    required_fields: dict[str, Any] | None = None,
) -> bool:
    record = component_record(name)
    heartbeat = read_json(health_path(name))
    if not record or not heartbeat:
        return False
    try:
        expected_pid = int(record.get("pid") or 0)
        heartbeat_pid = int(heartbeat.get("pid") or 0)
        age = time.time() - float(heartbeat.get("timestamp") or 0)
    except (TypeError, ValueError):
        return False
    if expected_pid <= 0 or heartbeat_pid != expected_pid:
        return False
    if age < -5 or age > max_age_seconds:
        return False
    if heartbeat.get("ready") is not True:
        return False
    for key, expected in dict(required_fields or {}).items():
        if heartbeat.get(key) != expected:
            return False
    return True


def write_component_record(spec: ComponentSpec, process: subprocess.Popen[Any]) -> None:
    try:
        create_time = psutil.Process(process.pid).create_time()
    except psutil.Error:
        create_time = time.time()
    atomic_json_write(
        pid_path(spec.name),
        {
            "component": spec.name,
            "pid": process.pid,
            "create_time": create_time,
            "command": spec.command,
            "cwd": str(spec.cwd),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def terminate_component(spec: ComponentSpec, reason: str) -> None:
    record = component_record(spec.name)
    if process_record_matches(record, spec):
        pid = int(record["pid"])
        LOG.event("component.stop", component=spec.name, pid=pid, reason=reason)
        try:
            proc = psutil.Process(pid)
            children = proc.children(recursive=True)
            for child in reversed(children):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            proc.terminate()
            _, alive = psutil.wait_procs([*children, proc], timeout=5)
            for item in alive:
                try:
                    item.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
    pid_path(spec.name).unlink(missing_ok=True)
    health_path(spec.name).unlink(missing_ok=True)


def resolved_addresses(host: str) -> list[str]:
    try:
        return sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)})
    except OSError:
        return []


def tls_ready(host: str, timeout: float = 2.0) -> bool:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host):
                return True
    except OSError:
        return False


def discord_network_ready() -> bool:
    return all(
        resolved_addresses(host) and tls_ready(host)
        for host in ("discord.com", "gateway.discord.gg")
    )


def lavalink_ready() -> bool:
    try:
        with socket.create_connection(("::1", 2333), timeout=0.35):
            return True
    except OSError:
        return False


def redbot_ready() -> bool:
    return heartbeat_ready(
        "redbot",
        max_age_seconds=15,
        required_fields={"audio_loaded": True, "discord_ready": True},
    )


def voice_ready() -> bool:
    return heartbeat_ready("voice", max_age_seconds=45)


def control_panel_ready() -> bool:
    try:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen("https://127.0.0.1:8765/api/healthz", timeout=1.0, context=context) as response:
            response.read()
            return response.status == 200
    except (OSError, ValueError):
        return False


def build_specs() -> list[ComponentSpec]:
    return [
        ComponentSpec(
            name="lavalink",
            command=[str(JAVA), "-Xms64M", "-Xmx512M", "-jar", str(LAVALINK_JAR)],
            cwd=LAVALINK_DIR,
            command_markers=("lavalink.jar", str(PROJECT_ROOT)),
            ready=lavalink_ready,
            ready_timeout=45,
        ),
        ComponentSpec(
            name="redbot",
            command=[str(BOT_PYTHON), str(REDBOT_SELECTOR)],
            cwd=PROJECT_ROOT,
            command_markers=("start_redbot_selector.py", str(PROJECT_ROOT)),
            ready=redbot_ready,
            ready_timeout=120,
        ),
        ComponentSpec(
            name="voice",
            command=[
                str(VOICE_PYTHON),
                "-m",
                "voice.djgoo_voice_listener",
                "--project-root",
                str(PROJECT_ROOT),
            ],
            cwd=PROJECT_ROOT,
            command_markers=("voice.djgoo_voice_listener", str(PROJECT_ROOT)),
            ready=voice_ready,
            ready_timeout=900,
        ),
        ComponentSpec(
            name="web",
            command=[
                str(BOT_PYTHON),
                "-m",
                "control_panel.server",
                "--project-root",
                str(PROJECT_ROOT),
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--tls",
            ],
            cwd=PROJECT_ROOT,
            command_markers=("control_panel.server", str(PROJECT_ROOT)),
            ready=control_panel_ready,
            ready_timeout=30,
        ),
    ]


def component_environment(resume_playback: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    # Hidden Windows processes inherit the workstation's legacy console code
    # page even though their output is redirected to UTF-8 log files. Force a
    # deterministic encoding so non-ASCII track titles cannot break logging.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8:backslashreplace"
    env["REDBOT_CONFIG_DIR"] = str(
        PROJECT_ROOT / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot"
    )
    env["DJGOO_SECRETS_FILE"] = str(PROJECT_ROOT / "config" / "secrets.json")
    env["DJGOO_EVENT_LOG"] = str(EVENT_LOG)
    env["DJGOO_HEALTH_DIR"] = str(HEALTH_DIR)
    if resume_playback:
        env["DJGOO_RESUME_PLAYBACK"] = "1"
        env["DJGOO_RESUME_ACTIVE_RADIO"] = "1"
    else:
        env.pop("DJGOO_RESUME_PLAYBACK", None)
        env.pop("DJGOO_RESUME_ACTIVE_RADIO", None)
    return env


def required_paths(spec: ComponentSpec) -> list[Path]:
    paths = [Path(spec.command[0])]
    if spec.name == "lavalink":
        paths.append(LAVALINK_JAR)
    elif spec.name == "redbot":
        paths.append(REDBOT_SELECTOR)
    return paths


def start_component(spec: ComponentSpec, *, resume_playback: bool = False) -> bool:
    if component_running(spec):
        return True
    missing = [path for path in required_paths(spec) if not path.exists()]
    if missing:
        LOG.event(
            "component.missing_dependency",
            component=spec.name,
            paths=[str(path) for path in missing],
        )
        return False

    COMPONENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    health_path(spec.name).unlink(missing_ok=True)
    stdout_path = COMPONENT_LOG_DIR / f"{spec.name}.out.log"
    stderr_path = COMPONENT_LOG_DIR / f"{spec.name}.err.log"
    LOG.event(
        "component.start",
        component=spec.name,
        command=spec.command,
        cwd=str(spec.cwd),
    )
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            spec.command,
            cwd=str(spec.cwd),
            env=component_environment(resume_playback=resume_playback),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=WINDOWS_DETACHED_FLAGS if os.name == "nt" else 0,
        )
    write_component_record(spec, process)
    return True


def wait_until_ready(spec: ComponentSpec) -> bool:
    deadline = time.monotonic() + spec.ready_timeout
    last_progress_log = 0.0
    while time.monotonic() < deadline:
        with STATE.lock:
            if not STATE.desired_running or STATE.shutdown_requested:
                return False
        if not component_running(spec):
            return False
        if spec.ready():
            LOG.event("component.ready", component=spec.name)
            return True
        now = time.monotonic()
        if now - last_progress_log >= 15:
            LOG.event(
                "component.waiting",
                component=spec.name,
                remaining_seconds=max(0, round(deadline - now)),
            )
            last_progress_log = now
        time.sleep(0.5)
    LOG.event(
        "component.ready_timeout",
        component=spec.name,
        timeout=spec.ready_timeout,
    )
    return False


def all_components_healthy(specs: list[ComponentSpec]) -> bool:
    return all(component_running(spec) and spec.ready() for spec in specs)


def persist_state() -> None:
    atomic_json_write(STATE_PATH, STATE.snapshot())


def update_component_status(specs: list[ComponentSpec]) -> None:
    status: dict[str, dict[str, Any]] = {}
    for spec in specs:
        record = component_record(spec.name) or {}
        running = component_running(spec)
        status[spec.name] = {
            "pid": int(record.get("pid") or 0),
            "running": running,
            "ready": bool(running and spec.ready()),
        }
    with STATE.lock:
        STATE.component_status = status
    persist_state()


def stop_stack(specs: list[ComponentSpec], reason: str) -> None:
    for spec in reversed(specs):
        terminate_component(spec, reason)
    with STATE.lock:
        STATE.component_status = {
            spec.name: {"pid": 0, "running": False, "ready": False}
            for spec in specs
        }
    persist_state()


def ensure_stack(specs: list[ComponentSpec], *, resume_playback: bool = False) -> None:
    if all_components_healthy(specs):
        with STATE.lock:
            STATE.last_error = ""
        update_component_status(specs)
        return

    if not discord_network_ready():
        with STATE.lock:
            STATE.last_error = "Discord network is not ready"
        LOG.event("network.not_ready")
        persist_state()
        return

    for spec in specs:
        with STATE.lock:
            if not STATE.desired_running or STATE.shutdown_requested:
                return
        if component_running(spec) and spec.ready():
            continue
        if component_running(spec):
            terminate_component(spec, "unhealthy-or-stale-heartbeat")
        if not start_component(spec, resume_playback=resume_playback):
            with STATE.lock:
                STATE.last_error = f"Could not start {spec.name}"
            persist_state()
            return
        if not wait_until_ready(spec):
            terminate_component(spec, "readiness-failed")
            with STATE.lock:
                STATE.last_error = f"{spec.name} did not become ready"
            persist_state()
            return

    with STATE.lock:
        STATE.last_error = ""
    update_component_status(specs)


def reconcile(specs: list[ComponentSpec]) -> None:
    with STATE.lock:
        reset = STATE.reset_requested
        desired = STATE.desired_running
        STATE.reset_requested = False
    if reset:
        stop_stack(specs, "reset")
        desired = True
    if not desired:
        stop_stack(specs, "requested-stop")
        return
    ensure_stack(specs, resume_playback=reset)


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            payload = json.loads(self.rfile.readline(64_000).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.wfile.write(b'{"ok":false,"error":"invalid request"}\n')
            return
        action = str(payload.get("action", "status")).lower()
        with STATE.lock:
            if action == "start":
                STATE.desired_running = True
                STATE.reset_requested = False
            elif action == "reset":
                STATE.desired_running = True
                STATE.reset_requested = True
            elif action == "stop":
                STATE.desired_running = False
                STATE.reset_requested = False
            elif action == "shutdown":
                STATE.desired_running = False
                STATE.shutdown_requested = True
            elif action != "status":
                response = {"ok": False, "error": f"unknown action: {action}"}
                self.wfile.write(json.dumps(response).encode("utf-8") + b"\n")
                return
        LOG.event("control.request", action=action)
        response = {"ok": True, "action": action, "state": STATE.snapshot()}
        self.wfile.write(json.dumps(response, default=str).encode("utf-8") + b"\n")


class ControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def write_supervisor_pid() -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    try:
        create_time = psutil.Process(os.getpid()).create_time()
    except psutil.Error:
        create_time = time.time()
    atomic_json_write(
        SUPERVISOR_PID_PATH,
        {
            "pid": os.getpid(),
            "create_time": create_time,
            "port": CONTROL_PORT,
            "project_root": str(PROJECT_ROOT),
            "version": STATE.version,
        },
    )


def run_supervisor() -> int:
    if not hasattr(sys.modules[__name__], "_djgoo_recovery_policy"):
        from tools.recovery_policy import install_recovery_policy

        install_recovery_policy(sys.modules[__name__])
    instance = SingleInstance(LOCK_PATH)
    if not instance.acquire():
        return 0
    write_supervisor_pid()
    specs = build_specs()
    LOG.event(
        "supervisor.started",
        pid=os.getpid(),
        port=CONTROL_PORT,
        components=[spec.name for spec in specs],
    )
    try:
        with ControlServer((CONTROL_HOST, CONTROL_PORT), ControlHandler) as server:
            thread = threading.Thread(
                target=server.serve_forever,
                name="djgoo-control",
                daemon=True,
            )
            thread.start()
            while True:
                reconcile(specs)
                with STATE.lock:
                    if STATE.shutdown_requested:
                        break
                time.sleep(2)
            stop_stack(specs, "supervisor-shutdown")
            server.shutdown()
            thread.join(timeout=2)
    finally:
        SUPERVISOR_PID_PATH.unlink(missing_ok=True)
        instance.close()
        LOG.event("supervisor.stopped")
    return 0


def control_request(action: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(json.dumps({"action": action}).encode("utf-8") + b"\n")
            with sock.makefile("rb") as fp:
                line = fp.readline(256_000)
        response = json.loads(line.decode("utf-8"))
        return response if isinstance(response, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def spawn_supervisor() -> bool:
    executable = PYTHONW if PYTHONW.exists() else Path(sys.executable)
    COMPONENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = COMPONENT_LOG_DIR / "supervisor.out.log"
    stderr_path = COMPONENT_LOG_DIR / "supervisor.err.log"
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        subprocess.Popen(
            [str(executable), str(Path(__file__).resolve()), "supervise"],
            cwd=str(PROJECT_ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=WINDOWS_DETACHED_FLAGS if os.name == "nt" else 0,
        )
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        if control_request("status", timeout=0.35):
            return True
        time.sleep(0.1)
    return False


def run_client(action: str) -> int:
    response = control_request(action)
    if response is None and action in {"start", "reset"}:
        if not spawn_supervisor():
            LOG.event("client.failed", action=action, reason="supervisor-unavailable")
            return 1
        response = control_request(action)
    if response is None:
        if action in {"stop", "shutdown"}:
            return 0
        print(json.dumps({"ok": False, "error": "DjGoo supervisor is not running"}))
        return 1
    if action == "status":
        print(json.dumps(response, indent=2, default=str))
    return 0 if response.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the supervised DjGoo stack.")
    parser.add_argument(
        "action",
        choices=("start", "stop", "reset", "status", "shutdown", "supervise"),
    )
    args = parser.parse_args()
    if args.action == "supervise":
        return run_supervisor()
    return run_client(args.action)


if __name__ == "__main__":
    raise SystemExit(main())
