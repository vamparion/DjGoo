from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path


BUNDLE_NAME = "DjGoo-Voice-update.zip"
MANIFEST_NAME = "DjGoo-Voice-update.json"
PRODUCT_NAME = "DjGoo Voice"
DIRECTORIES = (
    "voice",
    "source/launcher",
    "runtime/python",
)
ROOT_FILES = (
    "DjGoo Voice.exe",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements-voice.txt",
    "manifest.json",
)
TOOL_FILES = (
    "tools/update_auth.py",
    "tools/update_client.py",
    "tools/voice_update_client.py",
    "tools/apply_update.py",
    "tools/apply_voice_update.py",
    "tools/portable_environment.py",
)
CONFIG_FILES = (
    "config/voice-corrections.example.json",
    "config/voice-remote.example.json",
)
EXCLUDED_PARTS = {"__pycache__", ".git", ".github"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".ps1", ".vbs"}
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", re.IGNORECASE)


class VoiceUpdateBundleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def eligible(relative: Path) -> bool:
    return not any(part in EXCLUDED_PARTS for part in relative.parts) and relative.suffix.lower() not in EXCLUDED_SUFFIXES


def collect_voice_update_files(package_root: Path) -> list[Path]:
    root = package_root.resolve()
    collected: dict[str, Path] = {}

    def add(path: Path) -> None:
        if not path.is_file():
            return
        relative = path.relative_to(root)
        if eligible(relative):
            collected[relative.as_posix()] = path

    for name in (*ROOT_FILES, *TOOL_FILES, *CONFIG_FILES):
        add(root / name)
    for directory_name in DIRECTORIES:
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            add(path)

    required = {
        "DjGoo Voice.exe",
        "manifest.json",
        "tools/apply_voice_update.py",
        "tools/voice_update_client.py",
    }
    missing = sorted(required.difference(collected))
    if missing:
        raise VoiceUpdateBundleError(f"The recipient package is missing update files: {missing}")
    return [collected[name] for name in sorted(collected)]


def build_voice_update_bundle(
    package_root: Path,
    output_zip: Path,
    output_manifest: Path,
    version: str,
) -> dict[str, object]:
    root = package_root.resolve()
    normalized = str(version).strip().lstrip("v")
    if not VERSION_PATTERN.fullmatch(normalized):
        raise VoiceUpdateBundleError(f"Invalid recipient update version: {version}")
    files = collect_voice_update_files(root)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_zip.unlink(missing_ok=True)

    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            archive.write(path, relative)
            entries.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    manifest: dict[str, object] = {
        "schema": 1,
        "product": PRODUCT_NAME,
        "version": normalized,
        "release_tag": f"v{normalized}",
        "bundle_asset": BUNDLE_NAME,
        "bundle_sha256": sha256_file(output_zip),
        "bundle_size": output_zip.stat().st_size,
        "runtime_generation": 3,
        "requires_full_install": False,
        "files": entries,
        "deletes": [],
    }
    temporary = output_manifest.with_suffix(output_manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output_manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a verified DjGoo Voice incremental update.")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build_voice_update_bundle(
        args.package_root.resolve(),
        args.output_zip.resolve(),
        args.output_manifest.resolve(),
        args.version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
