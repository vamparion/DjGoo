from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from tools.update_client import (
    AuthenticationRequired,
    UpdateError,
    UpdateOffer,
    Version,
    _asset_map,
    _sha256,
    download_asset,
    fetch_releases,
    parse_version,
    read_installed_version,
)


MANIFEST_ASSET_NAME = "DjGoo-Voice-update.json"
BUNDLE_ASSET_NAME = "DjGoo-Voice-update.zip"
PRODUCT_NAME = "DjGoo Voice"
PROTECTED_PATHS = {
    "config/update-auth.json",
    "config/voice-remote.json",
    "data/voice-remote-credential.json",
    "data/voice-remote.pid",
}
PROTECTED_PREFIXES = (
    "data/models/",
    "logs/",
    "runtime/",
)


def select_voice_update(
    releases: Iterable[Mapping[str, object]],
    installed: Version,
    *,
    include_prereleases: bool | None = None,
) -> UpdateOffer | None:
    allow_prereleases = (
        installed.is_prerelease
        if include_prereleases is None
        else include_prereleases
    )
    candidates: list[UpdateOffer] = []
    for release in releases:
        if bool(release.get("draft")):
            continue
        if bool(release.get("prerelease")) and not allow_prereleases:
            continue
        tag = str(release.get("tag_name") or "").strip()
        version = parse_version(tag)
        if version is None or version <= installed:
            continue
        assets = _asset_map(release)
        manifest = assets.get(MANIFEST_ASSET_NAME)
        bundle = assets.get(BUNDLE_ASSET_NAME)
        if manifest is None or bundle is None:
            continue
        candidates.append(
            UpdateOffer(
                tag=tag,
                version=version,
                release_name=str(release.get("name") or tag),
                published_at=str(release.get("published_at") or ""),
                manifest_asset=manifest,
                bundle_asset=bundle,
            )
        )
    return max(candidates, key=lambda offer: offer.version) if candidates else None


def check_for_voice_update(
    project_root: Path,
    token: str | None = None,
) -> UpdateOffer | None:
    return select_voice_update(
        fetch_releases(token),
        read_installed_version(project_root),
    )


def read_runtime_generation(project_root: Path) -> int:
    root = project_root.resolve()
    for path in (
        root / "data" / "installed-version.json",
        root / "manifest.json",
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            generation = int(payload.get("runtime_generation") or 0)
        except (TypeError, ValueError):
            continue
        if generation > 0:
            return generation
    return 0


def _manifest_paths(payload: object, field: str) -> list[str]:
    if not isinstance(payload, list):
        if field == "files":
            raise UpdateError("The recipient update does not list any files")
        raise UpdateError(f"The recipient update {field} field is invalid")
    paths: list[str] = []
    for item in payload:
        value = item.get("path") if isinstance(item, dict) else item
        path = str(value or "").strip().replace("\\", "/")
        if not path:
            raise UpdateError(
                f"The recipient update contains an invalid {field} path"
            )
        paths.append(path)
    return paths


def _validate_protected_paths(paths: Iterable[str]) -> None:
    for path in paths:
        lowered = path.lower()
        if lowered in PROTECTED_PATHS or lowered.startswith(PROTECTED_PREFIXES):
            raise UpdateError(
                f"The recipient update attempts to replace protected local state: {path}"
            )


def validate_voice_manifest(
    payload: object,
    offer: UpdateOffer,
    *,
    installed_runtime_generation: int = 0,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise UpdateError("The recipient update manifest is not a JSON object")
    try:
        schema = int(payload.get("schema", 0))
    except (TypeError, ValueError):
        schema = 0
    if schema != 1:
        raise UpdateError(
            f"Unsupported recipient update manifest schema: {schema}"
        )
    if str(payload.get("product") or "") != PRODUCT_NAME:
        raise UpdateError("The update manifest is for a different DjGoo product")
    if str(payload.get("release_tag") or "") != offer.tag:
        raise UpdateError(
            "The recipient update manifest tag does not match the release"
        )
    if str(payload.get("bundle_asset") or "") != BUNDLE_ASSET_NAME:
        raise UpdateError(
            "The recipient update manifest references an unexpected bundle"
        )
    version = parse_version(str(payload.get("version") or ""))
    if version is None or version != offer.version:
        raise UpdateError("The recipient update version does not match the release")
    if bool(payload.get("requires_full_install")):
        raise UpdateError(
            "This DjGoo Voice update requires a new full recipient package"
        )
    try:
        manifest_generation = int(payload.get("runtime_generation") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError(
            "The recipient update has an invalid runtime generation"
        ) from exc
    if manifest_generation <= 0:
        raise UpdateError("The recipient update has an invalid runtime generation")
    if (
        installed_runtime_generation > 0
        and manifest_generation != installed_runtime_generation
    ):
        raise UpdateError(
            "This DjGoo Voice update requires a full package because its embedded runtime changed"
        )

    bundle_hash = str(payload.get("bundle_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", bundle_hash):
        raise UpdateError("The recipient update has an invalid bundle SHA-256")
    try:
        bundle_size = int(payload.get("bundle_size") or 0)
    except (TypeError, ValueError) as exc:
        raise UpdateError("The recipient update has an invalid bundle size") from exc
    if bundle_size <= 0:
        raise UpdateError("The recipient update has an invalid bundle size")

    file_paths = _manifest_paths(payload.get("files"), "files")
    if not file_paths:
        raise UpdateError("The recipient update does not list any files")
    delete_paths = _manifest_paths(payload.get("deletes", []), "deletes")
    _validate_protected_paths((*file_paths, *delete_paths))
    return dict(payload)


def download_voice_update(
    project_root: Path,
    offer: UpdateOffer,
    token: str | None = None,
    progress=None,
) -> tuple[Path, Path, dict[str, object]]:
    root = project_root.resolve()
    updates_dir = root / "data" / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    safe_tag = re.sub(r"[^0-9A-Za-z._-]+", "-", offer.tag)
    manifest_path = updates_dir / f"{safe_tag}-{MANIFEST_ASSET_NAME}"
    bundle_path = updates_dir / f"{safe_tag}-{BUNDLE_ASSET_NAME}"

    download_asset(offer.manifest_asset, manifest_path, token)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(
            "The downloaded recipient update manifest is invalid"
        ) from exc
    manifest = validate_voice_manifest(
        payload,
        offer,
        installed_runtime_generation=read_runtime_generation(root),
    )

    download_asset(offer.bundle_asset, bundle_path, token, progress)
    if bundle_path.stat().st_size != int(manifest["bundle_size"]):
        raise UpdateError(
            "The recipient update bundle size does not match its manifest"
        )
    if _sha256(bundle_path) != str(manifest["bundle_sha256"]).lower():
        raise UpdateError(
            "The recipient update bundle SHA-256 verification failed"
        )
    return bundle_path, manifest_path, manifest


__all__ = [
    "AuthenticationRequired",
    "UpdateError",
    "UpdateOffer",
    "check_for_voice_update",
    "download_voice_update",
    "read_runtime_generation",
    "select_voice_update",
    "validate_voice_manifest",
]
