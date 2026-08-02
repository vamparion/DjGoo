from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import traceback
from collections.abc import Iterable, Mapping
from pathlib import Path

from tools.apply_update import (
    _write_json,
    apply_staged_update,
    extract_verified_bundle,
    validate_bundle,
    wait_for_process_exit,
)
from tools.portable_environment import clean_subprocess_environment


PRODUCT_NAME = "DjGoo Voice"
LAUNCHER_NAME = "DjGoo Voice.exe"


def load_voice_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read recipient update manifest: {path}") from exc
    if not isinstance(payload, dict) or int(payload.get("schema", 0)) != 1:
        raise RuntimeError("Unsupported or invalid recipient update manifest")
    if payload.get("product") != PRODUCT_NAME:
        raise RuntimeError("Recipient update manifest is for a different product")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Recipient update manifest does not list any files")
    return payload


def stop_voice_listener(root: Path) -> None:
    path = root / "data" / "voice-remote.pid"
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    path.unlink(missing_ok=True)


def restart_voice(root: Path, log) -> None:
    launcher = root / LAUNCHER_NAME
    if not launcher.exists():
        log(f"Recipient restart skipped because {LAUNCHER_NAME} is missing.")
        return
    try:
        subprocess.Popen(
            [str(launcher)],
            cwd=root,
            env=clean_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
    except OSError as exc:
        log(f"Could not restart DjGoo Voice: {exc}")


def run_voice_update(root: Path, bundle: Path, manifest_path: Path, parent_pid: int) -> int:
    root = root.resolve()
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "update.log"
    result_path = root / "data" / "update-result.json"

    def log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    started_at = time.time()
    staging = root / "data" / "updates" / f"voice-staging-{os.getpid()}"
    try:
        stop_voice_listener(root)
        manifest = load_voice_manifest(manifest_path)
        expected = validate_bundle(bundle, manifest)
        version = str(manifest.get("version") or "unknown")
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
        _write_json(
            result_path,
            {
                "schema": 1,
                "success": True,
                "version": version,
                "started_at": started_at,
                "finished_at": time.time(),
                "backup": str(backup),
            },
        )
        shutil.rmtree(staging, ignore_errors=True)
        log(f"Successfully installed DjGoo Voice {version}.")
        restart_voice(root, log)
        return 0
    except BaseException as exc:
        log("Recipient update failed:\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        try:
            _write_json(
                result_path,
                {
                    "schema": 1,
                    "success": False,
                    "error": str(exc),
                    "started_at": started_at,
                    "finished_at": time.time(),
                },
            )
        except OSError:
            pass
        restart_voice(root, log)
        return 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a verified DjGoo Voice update.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_voice_update(args.root, args.bundle, args.manifest, args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())
