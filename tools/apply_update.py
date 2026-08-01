from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
import zipfile
from ctypes import wintypes
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping


REPLACE_TIMEOUT_SECONDS = 30.0
PARENT_EXIT_TIMEOUT_SECONDS = 30.0
PROCESS_SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF


class UpdateApplyError(RuntimeError):
    pass


def safe_relative_path(value: str) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    posix = PurePosixPath(text)
    if not text or text.startswith("/") or posix.is_absolute():
        raise UpdateApplyError(f"Unsafe update path: {value!r}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise UpdateApplyError(f"Unsafe update path: {value!r}")
    if ":" in posix.parts[0]:
        raise UpdateApplyError(f"Unsafe update path: {value!r}")
    return Path(*posix.parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateApplyError(f"Could not read update manifest: {path}") from exc
    if not isinstance(payload, dict) or int(payload.get("schema", 0)) != 1:
        raise UpdateApplyError("Unsupported or invalid update manifest")
    if payload.get("product") != "DjGoo Host":
        raise UpdateApplyError("Update manifest is for a different product")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateApplyError("Update manifest does not list any files")
    return payload


def manifest_files(manifest: Mapping[str, object]) -> dict[Path, dict[str, object]]:
    result: dict[Path, dict[str, object]] = {}
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise UpdateApplyError("Update manifest files field is invalid")
    for item in raw_files:
        if not isinstance(item, dict):
            raise UpdateApplyError("Update manifest contains an invalid file entry")
        relative = safe_relative_path(str(item.get("path") or ""))
        if relative in result:
            raise UpdateApplyError(f"Update manifest lists {relative} more than once")
        try:
            size = int(item.get("size"))
        except (TypeError, ValueError) as exc:
            raise UpdateApplyError(f"Invalid size for {relative}") from exc
        digest = str(item.get("sha256") or "").lower()
        if size < 0 or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise UpdateApplyError(f"Invalid hash metadata for {relative}")
        result[relative] = {"size": size, "sha256": digest}
    return result


def manifest_deletes(manifest: Mapping[str, object]) -> list[Path]:
    raw = manifest.get("deletes", [])
    if not isinstance(raw, list):
        raise UpdateApplyError("Update manifest deletes field is invalid")
    deletes: list[Path] = []
    for value in raw:
        relative = safe_relative_path(str(value))
        if relative not in deletes:
            deletes.append(relative)
    return deletes


def validate_bundle(bundle: Path, manifest: Mapping[str, object]) -> dict[Path, dict[str, object]]:
    expected_hash = str(manifest.get("bundle_sha256") or "").lower()
    expected_size = int(manifest.get("bundle_size") or 0)
    if bundle.stat().st_size != expected_size:
        raise UpdateApplyError("Update bundle size does not match its manifest")
    if sha256_file(bundle) != expected_hash:
        raise UpdateApplyError("Update bundle SHA-256 does not match its manifest")

    expected = manifest_files(manifest)
    with zipfile.ZipFile(bundle, "r") as archive:
        actual: set[Path] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = safe_relative_path(info.filename)
            if relative in actual:
                raise UpdateApplyError(f"Update bundle contains duplicate path {relative}")
            actual.add(relative)
            metadata = expected.get(relative)
            if metadata is None:
                raise UpdateApplyError(f"Update bundle contains unlisted file {relative}")
            if info.file_size != int(metadata["size"]):
                raise UpdateApplyError(f"Update bundle size mismatch for {relative}")
        missing = set(expected).difference(actual)
        if missing:
            raise UpdateApplyError(f"Update bundle is missing {sorted(map(str, missing))[0]}")
    return expected


def extract_verified_bundle(
    bundle: Path,
    staging: Path,
    expected: Mapping[Path, Mapping[str, object]],
) -> None:
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle, "r") as archive:
        for relative, metadata in expected.items():
            info = archive.getinfo(relative.as_posix())
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with archive.open(info, "r") as source, destination.open("wb") as output:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
                    written += len(block)
            if written != int(metadata["size"]) or digest.hexdigest() != str(metadata["sha256"]):
                raise UpdateApplyError(f"Extracted file verification failed for {relative}")


def _wait_for_windows_process(pid: int, timeout: float) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:
            return
        raise UpdateApplyError(f"Could not wait for DjGoo launcher process {pid} (Windows error {error})")
    try:
        result = kernel32.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
    finally:
        kernel32.CloseHandle(handle)
    if result == WAIT_OBJECT_0:
        return
    if result == WAIT_TIMEOUT:
        raise UpdateApplyError(f"DjGoo launcher process {pid} did not exit in time")
    if result == WAIT_FAILED:
        raise UpdateApplyError(
            f"Could not wait for DjGoo launcher process {pid} (Windows error {ctypes.get_last_error()})"
        )
    raise UpdateApplyError(f"Unexpected wait result {result} for DjGoo launcher process {pid}")


def _process_exists_posix(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wait_for_process_exit(pid: int, timeout: float = PARENT_EXIT_TIMEOUT_SECONDS) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        _wait_for_windows_process(pid, timeout)
        return
    deadline = time.monotonic() + timeout
    while _process_exists_posix(pid):
        if time.monotonic() >= deadline:
            raise UpdateApplyError(f"DjGoo launcher process {pid} did not exit in time")
        time.sleep(0.2)


def _atomic_copy(source: Path, destination: Path, timeout: float = REPLACE_TIMEOUT_SECONDS) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".djgoo-update-{os.getpid()}.tmp")
    deadline = time.monotonic() + timeout
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
            if time.monotonic() >= deadline:
                raise UpdateApplyError(f"Could not replace {destination}: {exc}") from exc
            time.sleep(0.4)


def _atomic_remove(path: Path, timeout: float = REPLACE_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while path.exists():
        try:
            path.unlink()
            return
        except (PermissionError, OSError) as exc:
            if time.monotonic() >= deadline:
                raise UpdateApplyError(f"Could not remove {path}: {exc}") from exc
            time.sleep(0.4)


def apply_staged_update(
    root: Path,
    staging: Path,
    manifest: Mapping[str, object],
    backup_root: Path,
) -> None:
    files = manifest_files(manifest)
    deletes = manifest_deletes(manifest)
    backup_root.mkdir(parents=True, exist_ok=True)
    replaced: list[Path] = []
    created: list[Path] = []
    removed: list[Path] = []

    try:
        for relative in files:
            source = staging / relative
            destination = root / relative
            backup = backup_root / relative
            if destination.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                replaced.append(relative)
            else:
                created.append(relative)
            _atomic_copy(source, destination)

        for relative in deletes:
            destination = root / relative
            if not destination.exists():
                continue
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            removed.append(relative)
            _atomic_remove(destination)
    except BaseException:
        rollback_errors: list[str] = []
        for relative in reversed(created):
            try:
                _atomic_remove(root / relative, timeout=5.0)
            except BaseException as exc:
                rollback_errors.append(f"remove {relative}: {exc}")
        for relative in reversed(replaced + removed):
            try:
                _atomic_copy(backup_root / relative, root / relative, timeout=5.0)
            except BaseException as exc:
                rollback_errors.append(f"restore {relative}: {exc}")
        if rollback_errors:
            raise UpdateApplyError("Update failed and rollback was incomplete: " + "; ".join(rollback_errors))
        raise


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stack_was_running(root: Path) -> bool:
    try:
        payload = json.loads((root / "data" / "djgoo-supervisor-state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("desired_running")) if isinstance(payload, dict) else False


def invoke_stack(root: Path, action: str, log: Callable[[str], None]) -> None:
    python = root / "runtime" / "python" / "python.exe"
    stack = root / "tools" / "djgoo_stack.py"
    if not python.exists() or not stack.exists():
        log(f"Stack {action} skipped because the runtime or supervisor is missing.")
        return
    try:
        completed = subprocess.run(
            [str(python), str(stack), action],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        log(f"Requested stack {action} (exit {completed.returncode}).")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"Stack {action} request could not complete: {exc}")


def restart_launcher(root: Path, log: Callable[[str], None]) -> None:
    launcher = root / "DjGoo.exe"
    if not launcher.exists():
        log("Launcher restart skipped because DjGoo.exe is missing.")
        return
    try:
        subprocess.Popen(
            [str(launcher)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
    except OSError as exc:
        log(f"Could not restart DjGoo: {exc}")


def run_update(root: Path, bundle: Path, manifest_path: Path, parent_pid: int) -> int:
    root = root.resolve()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "update.log"
    result_path = root / "data" / "update-result.json"

    def log(message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{stamp}] {message}\n")

    started_at = time.time()
    resume_stack = stack_was_running(root)
    invoke_stack(root, "stop", log)
    try:
        manifest = load_manifest(manifest_path)
        expected = validate_bundle(bundle, manifest)
        version = str(manifest.get("version") or "unknown")
        staging = root / "data" / "updates" / f"staging-{os.getpid()}"
        backup = root / "data" / "update-backups" / f"{time.strftime('%Y%m%d-%H%M%S')}-{version}"
        extract_verified_bundle(bundle, staging, expected)
        wait_for_process_exit(parent_pid)
        apply_staged_update(root, staging, manifest, backup)
        _write_json(
            root / "data" / "installed-version.json",
            {
                "schema": 1,
                "version": version,
                "release_tag": str(manifest.get("release_tag") or ""),
                "runtime_generation": int(manifest.get("runtime_generation") or 1),
                "installed_at": time.time(),
            },
        )
        if resume_stack:
            invoke_stack(root, "start", log)
        _write_json(
            result_path,
            {
                "schema": 1,
                "success": True,
                "version": version,
                "started_at": started_at,
                "finished_at": time.time(),
                "backup": str(backup),
                "resumed_stack": resume_stack,
            },
        )
        log(f"Successfully installed DjGoo {version}.")
        shutil.rmtree(staging, ignore_errors=True)
        restart_launcher(root, log)
        return 0
    except BaseException as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log("Update failed:\n" + detail)
        if resume_stack:
            invoke_stack(root, "start", log)
        try:
            _write_json(
                result_path,
                {
                    "schema": 1,
                    "success": False,
                    "error": str(exc),
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "resumed_stack": resume_stack,
                },
            )
        except OSError:
            pass
        restart_launcher(root, log)
        return 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a verified DjGoo incremental update.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_update(args.root, args.bundle, args.manifest, args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())
