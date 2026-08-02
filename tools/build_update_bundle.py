from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Iterable


DIRECTORY_PREFIXES = (
    "tools",
    "voice",
    "local_cogs",
    "control_panel",
    "control_panel_dist",
    "launcher",
)
LAUNCHER_FILES = (
    "DjGoo.exe",
    "DjGoo Mini Player.exe",
)
LAUNCHER_DEFERRED_VERSIONS = {
    "0.3.0-alpha.19",
    "0.3.0-alpha.20",
}
SELF_BOOTSTRAP_VERSIONS = {
    "0.3.0-alpha.20",
}
SELF_BOOTSTRAP_FILES = {
    "tools/pending_launchers/DjGoo.exe",
    "tools/pending_launchers/DjGoo Mini Player.exe",
    "tools/complete_launcher_update.py",
    "tools/djgoo_stack.py",
    "tools/apply_update.py",
}
ROOT_FILES = (
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements-bot.txt",
    "requirements-voice.txt",
    "pyproject.toml",
    "sbom.cdx.json",
    "data/installed-version.json",
    "data/lavalink-contract.json",
    "data/discordbot/cogs/Audio/Lavalink.jar",
    "data/discordbot/cogs/Audio/application.yml",
)
CONFIG_FILES = (
    "config/secrets.example.json",
    "config/voice-corrections.example.json",
)
EXCLUDED_PARTS = {"__pycache__", ".git", ".github"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
BUNDLE_NAME = "DjGoo-Host-update.zip"
MANIFEST_NAME = "DjGoo-Host-update.json"
SAFE_DATA_FILES = {
    "data/installed-version.json",
    "data/lavalink-contract.json",
    "data/discordbot/cogs/Audio/Lavalink.jar",
    "data/discordbot/cogs/Audio/application.yml",
}
VERSION_PATTERN = re.compile(
    r"\d+\.\d+\.\d+"
    r"(?:-(?:(?:alpha|beta|rc)\.\d+|dev))?"
    r"(?:\+[0-9A-Za-z.-]+)?",
    re.IGNORECASE,
)


class UpdateBundleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _eligible(path: Path) -> bool:
    return (
        not any(part in EXCLUDED_PARTS for part in path.parts)
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


def _directory_files(
    package_root: Path,
    relative_directory: str,
) -> Iterable[Path]:
    directory = package_root / relative_directory
    if not directory.exists():
        return ()
    return (
        path
        for path in directory.rglob("*")
        if path.is_file()
        and _eligible(path.relative_to(package_root))
    )


def _stage_self_bootstrap_launchers(package_root: Path) -> None:
    root = package_root.resolve()
    missing = [
        relative
        for relative in (
            *LAUNCHER_FILES,
            "tools/complete_launcher_update.py",
            "tools/djgoo_stack.py",
            "tools/apply_update.py",
        )
        if not (root / relative).is_file()
    ]
    if missing:
        raise UpdateBundleError(
            "The package cannot create a self-bootstrapping launcher update; "
            f"missing: {missing}"
        )

    pending = root / "tools" / "pending_launchers"
    shutil.rmtree(pending, ignore_errors=True)
    pending.mkdir(parents=True, exist_ok=True)
    for filename in LAUNCHER_FILES:
        shutil.copy2(root / filename, pending / filename)


def collect_update_files(
    package_root: Path,
    *,
    include_launchers: bool = True,
) -> list[Path]:
    root = package_root.resolve()
    collected: dict[str, Path] = {}

    def add(path: Path) -> None:
        if not path.is_file():
            return
        relative = path.relative_to(root).as_posix()
        if not _eligible(Path(relative)):
            return
        if relative.startswith("data/") and relative not in SAFE_DATA_FILES:
            return
        if relative.startswith(("logs/", ".localappdata/")):
            return
        if relative == "config/secrets.json":
            return
        collected[relative] = path

    if include_launchers:
        for filename in LAUNCHER_FILES:
            add(root / filename)
    for filename in ROOT_FILES:
        add(root / filename)
    for filename in CONFIG_FILES:
        add(root / filename)
    for directory in DIRECTORY_PREFIXES:
        for path in _directory_files(root, directory):
            add(path)

    site_packages = root / "runtime" / "python" / "Lib" / "site-packages"
    pip_package = site_packages / "pip"
    for path in _directory_files(
        root,
        pip_package.relative_to(root).as_posix(),
    ):
        add(path)
    if site_packages.exists():
        for dist_info in site_packages.glob("pip-*.dist-info"):
            if dist_info.is_dir():
                for path in _directory_files(
                    root,
                    dist_info.relative_to(root).as_posix(),
                ):
                    add(path)

    required = {
        "control_panel/state.py",
        "data/installed-version.json",
        "data/lavalink-contract.json",
        "data/discordbot/cogs/Audio/Lavalink.jar",
        "data/discordbot/cogs/Audio/application.yml",
        "tools/apply_update.py",
        "tools/djgoo_stack.py",
        "tools/djgoo_stack_core.py",
    }
    if include_launchers:
        required.update(LAUNCHER_FILES)
    missing = sorted(required.difference(collected))
    if missing:
        raise UpdateBundleError(
            f"The package is missing required update files: {missing}"
        )
    if not any(
        name.startswith("runtime/python/Lib/site-packages/pip/")
        for name in collected
    ):
        raise UpdateBundleError(
            "The package does not contain the bundled pip module"
        )
    return [collected[name] for name in sorted(collected)]


def build_update_bundle(
    package_root: Path,
    output_zip: Path,
    output_manifest: Path,
    version: str,
    *,
    include_launchers: bool = True,
) -> dict[str, object]:
    root = package_root.resolve()
    normalized_version = str(version).strip().lstrip("v")
    if not VERSION_PATTERN.fullmatch(normalized_version):
        raise UpdateBundleError(f"Invalid update version: {version}")
    if normalized_version in LAUNCHER_DEFERRED_VERSIONS:
        include_launchers = False

    self_bootstrap = bool(
        not include_launchers
        and normalized_version in SELF_BOOTSTRAP_VERSIONS
    )
    if self_bootstrap:
        _stage_self_bootstrap_launchers(root)

    files = collect_update_files(
        root,
        include_launchers=include_launchers,
    )
    relative_files = {
        path.relative_to(root).as_posix()
        for path in files
    }
    if self_bootstrap:
        missing_bootstrap = sorted(
            SELF_BOOTSTRAP_FILES.difference(relative_files)
        )
        if missing_bootstrap:
            raise UpdateBundleError(
                "The self-bootstrapping update is incomplete: "
                f"{missing_bootstrap}"
            )

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_zip.unlink()
    except FileNotFoundError:
        pass

    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(
        output_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
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
        "product": "DjGoo Host",
        "version": normalized_version,
        "release_tag": f"v{normalized_version}",
        "bundle_asset": BUNDLE_NAME,
        "bundle_sha256": sha256_file(output_zip),
        "bundle_size": output_zip.stat().st_size,
        "runtime_generation": 3,
        "requires_full_install": False,
        "launcher_update_deferred": not include_launchers,
        "launcher_completion_mode": (
            "portable-stack" if self_bootstrap else ""
        ),
        "files": entries,
        "deletes": [],
    }
    temporary = output_manifest.with_suffix(
        output_manifest.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output_manifest)
    if self_bootstrap:
        shutil.rmtree(
            root / "tools" / "pending_launchers",
            ignore_errors=True,
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a verified incremental DjGoo Host update."
    )
    parser.add_argument(
        "--package-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-zip",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--defer-launchers",
        action="store_true",
        help=(
            "Build a bootstrap update that installs the updater engine and "
            "supporting files without replacing the running one-file launchers."
        ),
    )
    args = parser.parse_args()
    build_update_bundle(
        args.package_root.resolve(),
        args.output_zip.resolve(),
        args.output_manifest.resolve(),
        args.version,
        include_launchers=not args.defer_launchers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
