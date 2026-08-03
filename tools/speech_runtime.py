from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Mapping

from tools.app_layout import speech_runtime_ready
from tools.update_auth import load_token
from tools.update_client import read_installed_version


REPOSITORY = "vamparion/DjGoo"
ZIP_NAME = "DjGoo-SpeechRuntime-win-x64.zip"
MANIFEST_NAME = "DjGoo-SpeechRuntime.json"


class SpeechRuntimeError(RuntimeError):
    pass


def _request(url: str, token: str | None, *, binary: bool = False) -> bytes:
    headers = {
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "User-Agent": "DjGoo-SpeechRuntime",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers),
            timeout=90,
        ) as response:
            return response.read()
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SpeechRuntimeError(f"Could not download DjGoo speech runtime: {exc}") from exc


def _release_assets(version: str, token: str | None) -> dict[str, Mapping[str, object]]:
    payload = json.loads(
        _request(
            f"https://api.github.com/repos/{REPOSITORY}/releases/tags/v{version}",
            token,
        ).decode("utf-8")
    )
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise SpeechRuntimeError("GitHub release does not contain an asset list")
    return {
        str(item.get("name") or ""): item
        for item in assets
        if isinstance(item, dict) and str(item.get("name") or "")
    }


def _asset_bytes(asset: Mapping[str, object], token: str | None) -> bytes:
    api_url = str(asset.get("url") or "")
    browser_url = str(asset.get("browser_download_url") or "")
    url = api_url if token and api_url else browser_url
    if not url:
        raise SpeechRuntimeError("GitHub returned an asset without a download URL")
    return _request(url, token, binary=bool(token and api_url))


def _safe_path(value: str) -> Path:
    posix = PurePosixPath(str(value).replace("\\", "/"))
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise SpeechRuntimeError(f"Unsafe speech runtime path: {value}")
    path = Path(*posix.parts)
    if path.parts[:2] != ("runtime", "speech"):
        raise SpeechRuntimeError(f"Speech runtime attempted to install outside runtime/speech: {value}")
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install_speech_runtime(root: Path, token: str | None = None) -> Path:
    root = root.resolve()
    version = read_installed_version(root).text
    resolved_token = token if token is not None else load_token(root / "config" / "update-auth.json")
    assets = _release_assets(version, resolved_token)
    missing = [name for name in (ZIP_NAME, MANIFEST_NAME) if name not in assets]
    if missing:
        raise SpeechRuntimeError(
            "The current DjGoo release has not finished publishing its optional "
            f"speech runtime: {', '.join(missing)}"
        )

    manifest_bytes = _asset_bytes(assets[MANIFEST_NAME], resolved_token)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpeechRuntimeError("Speech runtime manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("product") != "DjGoo Speech Runtime":
        raise SpeechRuntimeError("Speech runtime manifest is for a different product")
    if str(manifest.get("version") or "") != version:
        raise SpeechRuntimeError("Speech runtime version does not match installed DjGoo")

    bundle = _asset_bytes(assets[ZIP_NAME], resolved_token)
    if len(bundle) != int(manifest.get("bundle_size") or 0):
        raise SpeechRuntimeError("Speech runtime size does not match its manifest")
    if _sha256(bundle) != str(manifest.get("bundle_sha256") or "").lower():
        raise SpeechRuntimeError("Speech runtime hash does not match its manifest")

    listed: dict[Path, Mapping[str, object]] = {}
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise SpeechRuntimeError("Speech runtime manifest contains no files")
    for item in raw_files:
        if not isinstance(item, dict):
            raise SpeechRuntimeError("Speech runtime manifest contains an invalid entry")
        listed[_safe_path(str(item.get("path") or ""))] = item

    updates = root / "data" / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    zip_path = updates / ZIP_NAME
    zip_path.write_bytes(bundle)
    staging_root = updates / "speech-runtime-stage"
    shutil.rmtree(staging_root, ignore_errors=True)
    staging_root.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        actual = {_safe_path(info.filename) for info in archive.infolist() if not info.is_dir()}
        if actual != set(listed):
            raise SpeechRuntimeError("Speech runtime archive membership does not match its manifest")
        for relative, metadata in listed.items():
            data = archive.read(relative.as_posix())
            if len(data) != int(metadata.get("size") or -1):
                raise SpeechRuntimeError(f"Speech runtime size mismatch for {relative}")
            if _sha256(data) != str(metadata.get("sha256") or "").lower():
                raise SpeechRuntimeError(f"Speech runtime hash mismatch for {relative}")
            destination = staging_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

    staged = staging_root / "runtime" / "speech"
    destination = root / "runtime" / "speech"
    backup = root / "runtime" / "speech.previous"
    shutil.rmtree(backup, ignore_errors=True)
    if destination.exists():
        os.replace(destination, backup)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, destination)
    except BaseException:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(staging_root, ignore_errors=True)
    if not speech_runtime_ready(root):
        raise SpeechRuntimeError("Speech runtime installed but failed its readiness check")
    return destination
