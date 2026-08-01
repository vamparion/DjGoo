from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import psutil


LAVALINK_PORT = 2333
_LISTEN_STATES = {str(psutil.CONN_LISTEN).upper(), "LISTEN"}


def _connection_port(connection: Any) -> int | None:
    local_address = getattr(connection, "laddr", None)
    value = getattr(local_address, "port", None)
    if value is None and isinstance(local_address, (tuple, list)) and len(local_address) >= 2:
        value = local_address[1]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _psutil_listener_owner_pids(port: int) -> set[int]:
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError, AttributeError):
        return set()

    owners: set[int] = set()
    for connection in connections:
        status = str(getattr(connection, "status", "")).upper()
        pid = getattr(connection, "pid", None)
        if _connection_port(connection) != int(port) or status not in _LISTEN_STATES:
            continue
        try:
            resolved_pid = int(pid or 0)
        except (TypeError, ValueError):
            continue
        if resolved_pid > 0:
            owners.add(resolved_pid)
    return owners


def _windows_listener_owner_pids(port: int) -> set[int]:
    """Read TCP listener PIDs through the Windows IP Helper API.

    This is the fallback for installations where psutil's per-process socket
    inspection is denied or returns no rows. GetExtendedTcpTable exposes the
    owning PID for both IPv4 and IPv6 listeners without relying on command-line
    or working-directory access to the Java process.
    """

    if os.name != "nt":
        return set()

    try:
        import ctypes
        from ctypes import wintypes

        class Tcp4OwnerPidRow(ctypes.Structure):
            _fields_ = [
                ("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        class Tcp6OwnerPidRow(ctypes.Structure):
            _fields_ = [
                ("ucLocalAddr", ctypes.c_ubyte * 16),
                ("dwLocalScopeId", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("ucRemoteAddr", ctypes.c_ubyte * 16),
                ("dwRemoteScopeId", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwState", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        get_extended_tcp_table = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
        get_extended_tcp_table.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
            wintypes.ULONG,
            ctypes.c_int,
            wintypes.ULONG,
        ]
        get_extended_tcp_table.restype = wintypes.DWORD
    except (AttributeError, OSError):
        return set()

    error_insufficient_buffer = 122
    owner_pid_listener_table = 3
    owners: set[int] = set()

    for family, row_type in (
        (socket.AF_INET, Tcp4OwnerPidRow),
        (socket.AF_INET6, Tcp6OwnerPidRow),
    ):
        size = wintypes.DWORD(0)
        result = int(
            get_extended_tcp_table(
                None,
                ctypes.byref(size),
                False,
                family,
                owner_pid_listener_table,
                0,
            )
        )
        if result not in {0, error_insufficient_buffer} or size.value <= 4:
            continue

        buffer = ctypes.create_string_buffer(size.value)
        result = int(
            get_extended_tcp_table(
                buffer,
                ctypes.byref(size),
                False,
                family,
                owner_pid_listener_table,
                0,
            )
        )
        if result != 0:
            continue

        count = int(wintypes.DWORD.from_buffer_copy(buffer.raw[:4]).value)
        offset = ctypes.sizeof(wintypes.DWORD)
        row_size = ctypes.sizeof(row_type)
        for index in range(count):
            start = offset + index * row_size
            end = start + row_size
            if end > len(buffer.raw):
                break
            row = row_type.from_buffer_copy(buffer.raw[start:end])
            local_port = socket.ntohs(int(row.dwLocalPort) & 0xFFFF)
            pid = int(row.dwOwningPid)
            if local_port == int(port) and pid > 0:
                owners.add(pid)

    return owners


def listener_owner_pids(port: int = LAVALINK_PORT) -> list[int]:
    owners = _psutil_listener_owner_pids(port)
    if os.name == "nt":
        owners.update(_windows_listener_owner_pids(port))
    owners.discard(os.getpid())
    return sorted(owners)


def _process_cmdline(process: Any) -> str:
    try:
        return " ".join(str(part) for part in process.cmdline()).lower()
    except (psutil.Error, OSError, TypeError):
        return ""


def _process_cwd(process: Any) -> Path | None:
    try:
        return Path(str(process.cwd())).resolve()
    except (psutil.Error, OSError, TypeError, ValueError):
        return None


def _process_is_java(process: Any) -> bool:
    candidates: list[str] = []
    for reader_name in ("name", "exe"):
        try:
            value = getattr(process, reader_name)()
        except (psutil.Error, OSError, TypeError, AttributeError):
            continue
        if value:
            candidates.append(Path(str(value)).name.lower())
    return any(value in {"java", "java.exe", "javaw.exe"} for value in candidates)


def _lavalink_directory(project_root: Path) -> Path:
    return (
        project_root.resolve()
        / "data"
        / "discordbot"
        / "cogs"
        / "Audio"
    ).resolve()


def _process_is_package_lavalink(process: Any, project_root: Path) -> bool:
    command = _process_cmdline(process)
    if "lavalink.jar" not in command:
        return False
    root = project_root.resolve()
    return str(root).lower() in command or _process_cwd(process) == _lavalink_directory(root)


def _terminate_process_tree(process: Any) -> None:
    try:
        children = process.children(recursive=True)
    except psutil.Error:
        children = []

    targets = [*reversed(children), process]
    for target in targets:
        try:
            target.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=5)
    for target in alive:
        try:
            target.kill()
        except psutil.Error:
            pass


def cleanup_lavalink_processes(
    project_root: Path,
    port: int = LAVALINK_PORT,
) -> list[int]:
    """Stop stale Lavalink processes before Red Audio starts its managed node.

    Exact socket ownership is authoritative. A listener PID is stopped when it
    is Java, while package-matching Lavalink processes are also removed even if
    they are failed bind attempts that no longer own the port.
    """

    processes: dict[int, Any] = {}
    owner_pids = set(listener_owner_pids(port))

    for pid in owner_pids:
        try:
            process = psutil.Process(pid)
        except psutil.Error:
            continue
        if _process_is_java(process) or _process_is_package_lavalink(process, project_root):
            processes[int(process.pid)] = process

    try:
        candidates = psutil.process_iter()
    except (psutil.Error, OSError):
        candidates = []
    for process in candidates:
        try:
            pid = int(process.pid)
            if pid == os.getpid():
                continue
            if _process_is_package_lavalink(process, project_root):
                processes[pid] = process
        except (psutil.Error, OSError, TypeError, ValueError):
            continue

    stopped: list[int] = []
    for pid, process in sorted(processes.items()):
        try:
            if not process.is_running():
                continue
        except psutil.Error:
            continue
        _terminate_process_tree(process)
        stopped.append(pid)
    return stopped
