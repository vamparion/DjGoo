from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import Iterable

from tools.apply_update import (
    UpdateApplyError,
    _same_windows_path,
    _terminate_verified_windows_process,
    _windows_process_image,
    wait_for_process_exit,
)
from tools.portable_environment import clean_subprocess_environment


TH32CS_SNAPPROCESS = 0x00000002
LOCK_STALE_SECONDS = 300.0
REPLACE_TIMEOUT_SECONDS = 30.0
RESTART_GRACE_SECONDS = 5.0
PENDING_DIRECTORY = Path("tools") / "pending_launchers"
LAUNCHER_NAMES = ("DjGoo.exe", "DjGoo Mini Player.exe")


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_ids() -> list[int]:
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot in {None, invalid_handle}:
        return []
    result: list[int] = []
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            pid = int(entry.th32ProcessID)
            if pid > 0 and pid != os.getpid():
                result.append(pid)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def pending_launchers(root: Path) -> dict[Path, Path]:
    project_root = root.resolve()
    pending = project_root / PENDING_DIRECTORY
    return {
        pending / name: project_root / name
        for name in LAUNCHER_NAMES
        if (pending / name).is_file()
    }


def matching_launcher_pids(root: Path) -> list[tuple[int, Path]]:
    project_root = root.resolve()
    expected = {
        (project_root / name).resolve()
        for name in LAUNCHER_NAMES
    }
    matches: list[tuple[int, Path]] = []
    for pid in _process_ids():
        image = _windows_process_image(pid)
        if not image:
            continue
        for path in expected:
            if _same_windows_path(image, path):
                matches.append((pid, path))
                break
    return matches


def stop_matching_launchers(root: Path, log) -> None:
    matches = matching_launcher_pids(root)
    for pid, expected in matches:
        try:
            _terminate_verified_windows_process(pid, expected)
        except UpdateApplyError as exc:
            log(f"Could not stop verified launcher PID {pid}: {exc}")
            raise
    for pid, _ in matches:
        try:
            wait_for_process_exit(pid, timeout=5.0)
        except UpdateApplyError as exc:
            log(f"Verified launcher PID {pid} did not exit: {exc}")
            raise


def _atomic_replace(source: Path, destination: Path, root: Path, log) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        destination.name + f".djgoo-launcher-{os.getpid()}.tmp"
    )
    deadline = time.monotonic() + REPLACE_TIMEOUT_SECONDS
    while True:
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            return
        except (PermissionError, OSError) as exc:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            stop_matching_launchers(root, log)
            if time.monotonic() >= deadline:
                raise UpdateApplyError(
                    f"Could not complete launcher replacement for {destination}: {exc}"
                ) from exc
            time.sleep(0.35)


def _acquire_lock(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return None
        if age <= LOCK_STALE_SECONDS:
            return None
        try:
            path.unlink()
        except OSError:
            return None
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None


def _restart_host_if_needed(root: Path, log) -> None:
    time.sleep(RESTART_GRACE_SECONDS)
    if matching_launcher_pids(root):
        log("The updated DjGoo launcher is already running.")
        return
    launcher = root.resolve() / "DjGoo.exe"
    if not launcher.is_file():
        raise UpdateApplyError("The completed DjGoo launcher is missing")
    subprocess.Popen(
        [str(launcher)],
        cwd=root,
        env=clean_subprocess_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(
            int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ),
        close_fds=True,
    )
    log("Restarted the updated DjGoo launcher.")


def complete_launcher_update(root: Path) -> bool:
    project_root = root.resolve()
    pending = pending_launchers(project_root)
    if not pending:
        return False

    logs = project_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "launcher-update.log"

    def log(message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{stamp}] {message}\n")

    lock_path = project_root / "data" / "launcher-update.lock"
    lock_fd = _acquire_lock(lock_path)
    if lock_fd is None:
        return False
    try:
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        os.close(lock_fd)
        lock_fd = -1
        log("Completing deferred DjGoo launcher replacement.")
        stop_matching_launchers(project_root, log)
        for source, destination in pending.items():
            _atomic_replace(source, destination, project_root, log)
            log(f"Installed {destination.name}.")
        shutil.rmtree(project_root / PENDING_DIRECTORY, ignore_errors=True)
        marker = project_root / "data" / "launcher-update-complete.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "completed_at": time.time(),
                    "launchers": sorted(path.name for path in pending.values()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _restart_host_if_needed(project_root, log)
        log("Deferred DjGoo launcher replacement completed.")
        return True
    finally:
        if lock_fd not in {None, -1}:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Complete a deferred DjGoo launcher replacement."
    )
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        complete_launcher_update(args.root)
    except BaseException as exc:
        logs = args.root.resolve() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "launcher-update.log").open("a", encoding="utf-8") as stream:
            stream.write(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Deferred launcher replacement failed: {type(exc).__name__}: {exc}\n"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
