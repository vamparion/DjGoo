from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON_DIRECTORIES = ("launcher", "tools", "voice")
HOST_DIRECTORIES = (
    "config",
    "control_panel",
    "control_panel_dist",
    "local_cogs",
    "relay",
)
VOICE_DIRECTORIES = ("config",)
ROOT_FILES = (
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements-bot.txt",
    "requirements-voice.txt",
    "requirements-voice-base.txt",
    "requirements-speech.txt",
    "requirements-webrtc.txt",
)
EXCLUDED_NAMES = {
    ".git",
    ".github",
    ".venv",
    ".voice-venv",
    "__pycache__",
    "node_modules",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".ps1", ".vbs"}


class AppLayerBuildError(RuntimeError):
    pass


def _ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        if name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
            ignored.add(name)
    return ignored


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=_ignore,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(output: Path, product: str, version: str) -> Path:
    files: list[dict[str, object]] = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        if relative == "app-layer.json":
            continue
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    payload = {
        "schema": 1,
        "kind": "djgoo-application-layer",
        "product": product,
        "version": version,
        "file_count": len(files),
        "files": files,
    }
    path = output / "app-layer.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def build(output: Path, product: str, version: str) -> Path:
    normalized_product = product.strip().lower()
    if normalized_product not in {"host", "voice"}:
        raise AppLayerBuildError(f"Unsupported DjGoo product: {product}")
    normalized_version = version.strip().lstrip("v")
    if not normalized_version:
        raise AppLayerBuildError("DjGoo version is empty")

    output = output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    directories = list(COMMON_DIRECTORIES)
    directories.extend(
        HOST_DIRECTORIES if normalized_product == "host" else VOICE_DIRECTORIES
    )
    for directory in directories:
        _copy_tree(PROJECT_ROOT / directory, output / directory)
    for filename in ROOT_FILES:
        source = PROJECT_ROOT / filename
        if source.is_file():
            shutil.copy2(source, output / filename)

    # Runtime state belongs at package root, never inside an immutable app layer.
    for private in (
        output / "config" / "secrets.json",
        output / "config" / "update-auth.json",
    ):
        private.unlink(missing_ok=True)
    for directory in (output / "data", output / "logs", output / ".localappdata"):
        shutil.rmtree(directory, ignore_errors=True)

    required = [
        output / "launcher",
        output / "tools" / "app_layout.py",
        output / "tools" / "portable_environment.py",
        output / "voice",
    ]
    if normalized_product == "host":
        required.extend(
            [
                output / "local_cogs" / "djgoowelcome",
                output / "tools" / "djgoo_portable_stack_entry.py",
                output / "tools" / "djgoo_stack.py",
            ]
        )
    missing = [str(path.relative_to(output)) for path in required if not path.exists()]
    if missing:
        raise AppLayerBuildError(f"Application layer is incomplete: {missing}")

    write_manifest(output, normalized_product, normalized_version)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a versioned DjGoo application layer.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product", choices=("host", "voice"), required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    path = build(args.output, args.product, args.version)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
