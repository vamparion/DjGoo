from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
RUN_LOG_DIR = LOG_DIR / "startup-runs"
PID_DIR = PROJECT_ROOT / "data" / "pids"
JAVA = Path(r"C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot\bin\java.exe")
BOT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
VOICE_PYTHON = PROJECT_ROOT / ".voice-venv" / "Scripts" / "python.exe"
REDBOT_SELECTOR = PROJECT_ROOT / "tools" / "start_redbot_selector.py"
LAVALINK_DIR = PROJECT_ROOT / "data" / "discordbot" / "cogs" / "Audio"
LAVALINK_JAR = LAVALINK_DIR / "Lavalink.jar"
REDBOT_LOG = PROJECT_ROOT / "data" / "discordbot" / "core" / "logs" / "red.log"
WINDOWS_DETACHED_FLAGS = 0
if os.name == "nt":
    WINDOWS_DETACHED_FLAGS = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )


def session_id(pid: int | None = None) -> int | None:
    if os.name != "nt":
        return None
    value = ctypes.c_ulong()
    target = os.getpid() if pid is None else pid
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.c_ulong(target), ctypes.byref(value))
    return int(value.value) if ok else None


class Logger:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.path = run_dir / "launcher.jsonl"
        self.text_path = LOG_DIR / "startup.log"

    def event(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
        with self.text_path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")


def new_logger() -> Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUN_LOG_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return Logger(run_dir)


def run_capture(command: list[str], *, cwd: Path = PROJECT_ROOT, timeout: int = 20, max_chars: int | None = 8000) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout if max_chars is None else completed.stdout[-max_chars:],
            "stderr": completed.stderr if max_chars is None else completed.stderr[-max_chars:],
        }
    except Exception as exc:
        return {"command": command, "error": type(exc).__name__, "detail": str(exc)}


def dns_servers() -> dict[str, Any]:
    return run_capture(
        ["ipconfig", "/all"],
        timeout=15,
    )


def ip_state() -> dict[str, Any]:
    return run_capture(
        ["netsh", "interface", "ipv4", "show", "interfaces"],
        timeout=15,
    )


def process_snapshot() -> dict[str, Any]:
    processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = proc.info
            processes.append(
                {
                    "ProcessId": info.get("pid"),
                    "ParentProcessId": info.get("ppid"),
                    "SessionId": session_id(int(info.get("pid") or 0)),
                    "Name": info.get("name"),
                    "ExecutablePath": info.get("exe"),
                    "CommandLine": " ".join(info.get("cmdline") or []),
                    "CreateTime": info.get("create_time"),
                }
            )
        except (psutil.Error, OSError, ValueError):
            continue
    return {"processes": processes}


def resolved_addresses(host: str) -> list[str]:
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)})
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


def wait_for_discord(log: Logger, *, timeout: int = 45) -> bool:
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        results = {host: {"addresses": resolved_addresses(host), "tls": tls_ready(host)} for host in ("discord.com", "gateway.discord.gg")}
        log.event("network.check", attempt=attempt, results=results)
        if all(result["addresses"] and result["tls"] for result in results.values()):
            log.event("network.ready", attempt=attempt)
            return True
        time.sleep(1)
    log.event("network.timeout", timeout=timeout)
    return False


def pid_path(name: str) -> Path:
    return PID_DIR / f"{name}.json"


def read_pid(name: str) -> dict[str, Any] | None:
    path = pid_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_pid(name: str, proc: subprocess.Popen, command: list[str], cwd: Path, log: Logger) -> None:
    data = {
        "component": name,
        "pid": proc.pid,
        "session_id": session_id(proc.pid),
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "command": command,
        "cwd": str(cwd),
        "run_log_dir": str(log.run_dir),
    }
    pid_path(name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.event("pid.written", **data)


def is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    return psutil.pid_exists(pid)


def process_children(pid: int) -> list[int]:
    try:
        return [child.pid for child in psutil.Process(pid).children(recursive=True)]
    except psutil.Error:
        return []


def process_command_line(proc: psutil.Process) -> str:
    try:
        return " ".join(proc.cmdline())
    except psutil.Error:
        return ""


def process_session_id(proc: psutil.Process) -> int | None:
    try:
        return session_id(proc.pid)
    except (psutil.Error, OSError):
        return None


def is_project_owned_process(proc: psutil.Process) -> bool:
    try:
        name = (proc.name() or "").lower()
    except psutil.Error:
        return False
    if name not in {"python.exe", "pythonw.exe", "java.exe"}:
        return False
    command_line = process_command_line(proc)
    if str(PROJECT_ROOT).lower() not in command_line.lower():
        return False
    lowered = command_line.lower()
    return (
        "djgoo_voice_listener" in lowered
        or "start_redbot_selector.py" in lowered
        or "lavalink.jar" in lowered
    )


def child_pids(pid: int) -> list[int]:
    return process_children(pid)


def project_owned_processes() -> list[dict[str, Any]]:
    owned: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "exe"]):
        try:
            if not is_project_owned_process(proc):
                continue
            owned.append(
                {
                    "ProcessId": proc.pid,
                    "ParentProcessId": proc.ppid(),
                    "SessionId": process_session_id(proc),
                    "Name": proc.name(),
                    "ExecutablePath": proc.exe(),
                    "CommandLine": process_command_line(proc),
                }
            )
        except psutil.Error:
            continue
    return owned


def stop_pid(pid: int, log: Logger, *, reason: str) -> None:
    log.event("process.stop", pid=pid, reason=reason)
    result = run_capture(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=8)
    log.event("process.stop.result", pid=pid, reason=reason, result=result)


def stop_pids(pids: list[int], log: Logger, *, reason: str) -> None:
    targets = sorted({pid for pid in pids if pid > 0 and pid != os.getpid()})
    if not targets:
        return
    command = ["taskkill"]
    for pid in targets:
        log.event("process.stop", pid=pid, reason=reason)
        command.extend(["/PID", str(pid)])
    command.extend(["/T", "/F"])
    result = run_capture(command, timeout=12)
    log.event("process.stop.result", pids=targets, reason=reason, result=result)


def stop_owned(log: Logger) -> None:
    targets: list[int] = []
    for name in ("voice", "redbot", "lavalink"):
        data = read_pid(name)
        if data and isinstance(data.get("pid"), int):
            pid = int(data["pid"])
            log.event("process.stop.queued", pid=pid, reason=f"stop-owned:{name}")
            targets.append(pid)
        pid_path(name).unlink(missing_ok=True)

    # Full command-line process scans are slow under ASTER/ProtoInput on this PC.
    # PID files are the primary ownership mechanism; taskkill /T handles children.
    if targets:
        log.event("process.discovery.skipped", reason="pid-files-present", pids=targets)
        stop_pids(targets, log, reason="stop-owned")
        log.event("stop.complete")
        return

    for proc in project_owned_processes():
        try:
            pid = int(proc.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid in targets or pid == os.getpid():
            continue
        log.event(
            "process.stop.discovered",
            pid=pid,
            name=proc.get("Name"),
            session_id=proc.get("SessionId"),
            command_line=proc.get("CommandLine"),
        )
        targets.append(pid)
    stop_pids(targets, log, reason="stop-owned")
    log.event("stop.complete")


def owned_stack_running(log: Logger) -> bool:
    status: dict[str, Any] = {}
    for name in ("lavalink", "redbot", "voice"):
        data = read_pid(name)
        pid = int(data.get("pid") or 0) if data else 0
        status[name] = {"pid": pid, "running": is_running(pid)}
    status["lavalink"]["listening"] = lavalink_ready() if status["lavalink"]["running"] else False
    ready = all(status[name]["running"] for name in ("lavalink", "redbot", "voice")) and bool(status["lavalink"]["listening"])
    log.event("stack.running_check", ready=ready, components=status)
    return ready


def start_process(
    name: str,
    command: list[str],
    cwd: Path,
    log: Logger,
    stdout_name: str,
    stderr_name: str,
    *,
    resume_playback: bool = False,
) -> subprocess.Popen:
    stdout_path = log.run_dir / stdout_name
    stderr_path = log.run_dir / stderr_name
    env = os.environ.copy()
    env["REDBOT_CONFIG_DIR"] = str(PROJECT_ROOT / ".localappdata" / "Red-DiscordBot" / "Red-DiscordBot")
    env["DJGOO_SECRETS_FILE"] = str(PROJECT_ROOT / "config" / "secrets.json")
    env["DJGOO_EVENT_LOG"] = str(LOG_DIR / "djgoo-events.jsonl")
    if resume_playback:
        env["DJGOO_RESUME_PLAYBACK"] = "1"
        env["DJGOO_RESUME_ACTIVE_RADIO"] = "1"
    log.event("process.start", component=name, command=command, cwd=str(cwd), stdout=str(stdout_path), stderr=str(stderr_path))
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    flags = WINDOWS_DETACHED_FLAGS if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=flags)
    except OSError as exc:
        if os.name != "nt" or not flags:
            raise
        log.event("process.start.detached_failed", component=name, error=type(exc).__name__, detail=str(exc), flags=flags)
        fallback_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=fallback_flags)
    finally:
        stdout.close()
        stderr.close()
    write_pid(name, proc, command, cwd, log)
    return proc


def lavalink_ready() -> bool:
    try:
        with socket.create_connection(("::1", 2333), timeout=0.25):
            return True
    except OSError:
        return False


def wait_lavalink(log: Logger, *, timeout: int = 45) -> bool:
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        ready = lavalink_ready()
        log.event("lavalink.check", attempt=attempt, ready=ready)
        if ready:
            log.event("lavalink.ready", attempt=attempt)
            return True
        time.sleep(0.5)
    log.event("lavalink.timeout", timeout=timeout)
    return False


def wait_redbot(log: Logger, *, timeout: int = 90) -> bool:
    start_size = REDBOT_LOG.stat().st_size if REDBOT_LOG.exists() else 0
    deadline = time.monotonic() + timeout
    seen_discord = False
    seen_lavalink = False
    while time.monotonic() < deadline:
        text = ""
        if REDBOT_LOG.exists():
            with REDBOT_LOG.open("r", encoding="utf-8", errors="replace") as fp:
                fp.seek(min(start_size, REDBOT_LOG.stat().st_size))
                text = fp.read()
        if "Connected to Discord. Getting ready" in text or "has connected to Gateway" in text or "successfully RESUMED" in text:
            seen_discord = True
        if "Lavalink WS connected" in text:
            seen_lavalink = True
        log.event("redbot.check", seen_discord=seen_discord, seen_lavalink=seen_lavalink)
        if seen_discord and seen_lavalink:
            log.event("redbot.ready")
            return True
        time.sleep(0.75)
    log.event("redbot.timeout", timeout=timeout, seen_discord=seen_discord, seen_lavalink=seen_lavalink)
    return False


def wait_voice(log: Logger, *, timeout: int = 30) -> bool:
    event_log = LOG_DIR / "djgoo-events.jsonl"
    start_size = event_log.stat().st_size if event_log.exists() else 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = ""
        if event_log.exists():
            with event_log.open("r", encoding="utf-8", errors="replace") as fp:
                fp.seek(min(start_size, event_log.stat().st_size))
                text = fp.read()
        ready = "voice.listener.ready" in text
        hotkey = "voice.hotkey.registration" in text
        log.event("voice.check", ready=ready, hotkey_registered=hotkey)
        if ready and (hotkey or '"push_to_talk": false' in text):
            log.event("voice.ready", hotkey_registered=hotkey)
            return True
        time.sleep(0.5)
    log.event("voice.timeout", timeout=timeout)
    return False


def log_environment(log: Logger) -> None:
    log.event(
        "startup.begin",
        project_root=str(PROJECT_ROOT),
        cwd=os.getcwd(),
        username=getpass.getuser(),
        userdomain=os.environ.get("USERDOMAIN"),
        session_id=session_id(),
        path=os.environ.get("PATH", ""),
        java=str(JAVA),
        java_exists=JAVA.exists(),
        bot_python=str(BOT_PYTHON),
        bot_python_exists=BOT_PYTHON.exists(),
        voice_python=str(VOICE_PYTHON),
        voice_python_exists=VOICE_PYTHON.exists(),
    )
    if os.environ.get("DJGOO_DEEP_STARTUP_LOG", "").strip() == "1":
        log.event("network.ip_state", result=ip_state())
        log.event("network.dns_servers", result=dns_servers())
        log.event("process.snapshot.begin", result=process_snapshot())


def start_stack(log: Logger, *, retries: int = 2, resume_playback: bool = False) -> int:
    log_environment(log)
    log.event("stack.start.mode", resume_playback=resume_playback)
    if not resume_playback and owned_stack_running(log):
        log.event("stack.already_running")
        return 0
    for attempt in range(1, retries + 1):
        log.event("stack.start.attempt", attempt=attempt, retries=retries)
        stop_owned(log)
        if not wait_for_discord(log):
            log.event("stack.retry", attempt=attempt, reason="network")
            continue
        if not JAVA.exists() or not LAVALINK_JAR.exists():
            log.event("stack.failed", reason="missing-java-or-lavalink", java_exists=JAVA.exists(), jar_exists=LAVALINK_JAR.exists())
            return 1
        start_process("lavalink", [str(JAVA), "-Xms64M", "-Xmx512M", "-jar", str(LAVALINK_JAR)], LAVALINK_DIR, log, "lavalink.out.log", "lavalink.err.log", resume_playback=resume_playback)
        if not wait_lavalink(log):
            log.event("stack.retry", attempt=attempt, reason="lavalink")
            continue
        start_process("redbot", [str(BOT_PYTHON), str(REDBOT_SELECTOR)], PROJECT_ROOT, log, "redbot.out.log", "redbot.err.log", resume_playback=resume_playback)
        if not wait_redbot(log):
            log.event("stack.retry", attempt=attempt, reason="redbot")
            continue
        if VOICE_PYTHON.exists():
            start_process("voice", [str(VOICE_PYTHON), "-m", "voice.djgoo_voice_listener", "--project-root", str(PROJECT_ROOT)], PROJECT_ROOT, log, "voice.out.log", "voice.err.log", resume_playback=resume_playback)
            if not wait_voice(log):
                log.event("stack.retry", attempt=attempt, reason="voice")
                continue
        log.event("stack.ready", attempt=attempt)
        return 0
    log.event("stack.failed", reason="retries-exhausted")
    log.event("process.snapshot.failed", result=process_snapshot())
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "reset"))
    args = parser.parse_args()
    log = new_logger()
    log.event("launcher.invoked", argv=sys.argv, action=args.action)
    if args.action == "stop":
        log_environment(log)
        stop_owned(log)
        return 0
    if args.action == "reset":
        log_environment(log)
        stop_owned(log)
        return start_stack(log, resume_playback=True)
    return start_stack(log, resume_playback=False)


if __name__ == "__main__":
    raise SystemExit(main())
