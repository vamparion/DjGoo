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


LEGACY_DIRECTORY_PREFIXES = (
    "tools",
    "voice",
    "local_cogs",
    "control_panel",
    "control_panel_dist",
    "launcher",
)
LAUNCHER_FILES = ("DjGoo.exe", "DjGoo Mini Player.exe")
LAUNCHER_DEFERRED_VERSIONS = {"0.3.0-alpha.19"}
SELF_BOOTSTRAP_MINIMUM = (0, 3, 0, 0, 20)
SELF_BOOTSTRAP_MAXIMUM = (0, 3, 0, 0, 25)
SELF_BOOTSTRAP_FILES = {
    "tools/pending_launchers/DjGoo.exe",
    "tools/pending_launchers/DjGoo Mini Player.exe",
    "tools/complete_launcher_update.py",
    "tools/djgoo_stack.py",
    "tools/apply_update.py",
}
LEGACY_ROOT_FILES = (
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
LEGACY_CONFIG_FILES = (
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


def _directory_files(package_root: Path, relative_directory: str) -> Iterable[Path]:
    directory = package_root / relative_directory
    if not directory.exists():
        return ()
    return (
        path
        for path in directory.rglob("*")
        if path.is_file() and _eligible(path.relative_to(package_root))
    )


def _version_key(value: str) -> tuple[int, int, int, int, int]:
    normalized = value.strip().lstrip("v").split("+", 1)[0]
    base, separator, prerelease = normalized.partition("-")
    try:
        major, minor, patch = (int(item) for item in base.split("."))
    except (TypeError, ValueError) as exc:
        raise UpdateBundleError(f"Invalid update version: {value}") from exc
    if not separator:
        return major, minor, patch, 3, 0
    if prerelease.lower() == "dev":
        return major, minor, patch, -1, 0
    try:
        channel, number_text = prerelease.lower().split(".", 1)
        number = int(number_text)
    except (TypeError, ValueError) as exc:
        raise UpdateBundleError(f"Invalid update version: {value}") from exc
    rank = {"alpha": 0, "beta": 1, "rc": 2}.get(channel)
    if rank is None:
        raise UpdateBundleError(f"Invalid update version: {value}")
    return major, minor, patch, rank, number


def _requires_self_bootstrap(version: str) -> bool:
    """Defer launchers only through the alpha.25 thin-launcher migration."""

    key = _version_key(version)
    return SELF_BOOTSTRAP_MINIMUM <= key <= SELF_BOOTSTRAP_MAXIMUM


def _stage_self_bootstrap_launchers(package_root: Path) -> None:
    root = package_root.resolve()
    required = (
        *LAUNCHER_FILES,
        "tools/complete_launcher_update.py",
        "tools/djgoo_stack.py",
        "tools/apply_update.py",
    )
    missing = [relative for relative in required if not (root / relative).is_file()]
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


def _is_layered(root: Path, version: str) -> bool:
    return bool(
        (root / "current.json").is_file()
        and (root / "app" / version).is_dir()
    )


def collect_layered_update_files(
    package_root: Path,
    version: str,
    *,
    include_launchers: bool,
) -> list[Path]:
    root = package_root.resolve()
    collected: dict[str, Path] = {}

    def add(path: Path) -> None:
        if not path.is_file():
            return
        relative = path.relative_to(root)
        if not _eligible(relative) or (
            relative.parts[:1] == ("runtime",)
            and relative.parts[:2] != ("runtime", "webrtc")
        ):
            return
        collected[relative.as_posix()] = path

    if include_launchers:
        for name in LAUNCHER_FILES:
            add(root / name)
    for name in ("current.json", "data/installed-version.json"):
        add(root / name)
    for directory in (f"app/{version}", "tools", "runtime/webrtc"):
        for path in _directory_files(root, directory):
            add(path)

    required = {
        "current.json",
        "data/installed-version.json",
        f"app/{version}/app-layer.json",
        f"app/{version}/launcher/djgoo_layered_host.py",
        f"app/{version}/tools/apply_update.py",
        "tools/apply_update.py",
        "tools/djgoo_stack.py",
        "runtime/webrtc/layer-manifest.json",
    }
    if include_launchers:
        required.update(LAUNCHER_FILES)
    missing = sorted(required.difference(collected))
    if missing:
        raise UpdateBundleError(f"Layered Host update is incomplete: {missing}")
    if any(
        name.startswith("runtime/") and not name.startswith("runtime/webrtc/")
        for name in collected
    ):
        raise UpdateBundleError("Host update contains an unapproved runtime layer")
    return [collected[name] for name in sorted(collected)]


def collect_legacy_update_files(
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
        if relative.startswith(("logs/", ".localappdata/")) or relative == "config/secrets.json":
            return
        collected[relative] = path

    if include_launchers:
        for filename in LAUNCHER_FILES:
            add(root / filename)
    for filename in LEGACY_ROOT_FILES:
        add(root / filename)
    for filename in LEGACY_CONFIG_FILES:
        add(root / filename)
    for directory in LEGACY_DIRECTORY_PREFIXES:
        for path in _directory_files(root, directory):
            add(path)

    site_packages = root / "runtime" / "python" / "Lib" / "site-packages"
    for path in _directory_files(root, (site_packages / "pip").relative_to(root).as_posix()):
        add(path)
    if site_packages.exists():
        for dist_info in site_packages.glob("pip-*.dist-info"):
            for path in _directory_files(root, dist_info.relative_to(root).as_posix()):
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
        raise UpdateBundleError(f"The package is missing required update files: {missing}")
    return [collected[name] for name in sorted(collected)]


def collect_update_files(
    package_root: Path,
    *,
    include_launchers: bool = True,
    version: str | None = None,
) -> list[Path]:
    root = package_root.resolve()
    normalized = str(version or "").strip().lstrip("v")
    if normalized and _is_layered(root, normalized):
        return collect_layered_update_files(
            root,
            normalized,
            include_launchers=include_launchers,
        )
    return collect_legacy_update_files(root, include_launchers=include_launchers)


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

    layered = _is_layered(root, normalized_version)
    self_bootstrap = _requires_self_bootstrap(normalized_version)
    if normalized_version in LAUNCHER_DEFERRED_VERSIONS or self_bootstrap:
        include_launchers = False
    pending = root / "tools" / "pending_launchers"

    try:
        if self_bootstrap:
            _stage_self_bootstrap_launchers(root)
        files = collect_update_files(
            root,
            include_launchers=include_launchers,
            version=normalized_version,
        )
        relative_files = {path.relative_to(root).as_posix() for path in files}
        if self_bootstrap:
            missing_bootstrap = sorted(SELF_BOOTSTRAP_FILES.difference(relative_files))
            if missing_bootstrap:
                raise UpdateBundleError(
                    f"The self-bootstrapping update is incomplete: {missing_bootstrap}"
                )

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        output_manifest.parent.mkdir(parents=True, exist_ok=True)
        output_zip.unlink(missing_ok=True)
        entries: list[dict[str, object]] = []
        with zipfile.ZipFile(
            output_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6 if layered else 9,
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
            "runtime_generation": 4 if layered else 3,
            "package_layout": "versioned-app-v1" if layered else "legacy-flat",
            "requires_full_install": False,
            "launcher_update_deferred": not include_launchers,
            "launcher_completion_mode": "portable-stack" if self_bootstrap else "",
            "files": entries,
            "deletes": [],
        }
        temporary = output_manifest.with_suffix(output_manifest.suffix + ".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, output_manifest)
        return manifest
    finally:
        if self_bootstrap:
            shutil.rmtree(pending, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a verified incremental DjGoo Host update.")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--defer-launchers", action="store_true")
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
