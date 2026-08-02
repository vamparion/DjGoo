from __future__ import annotations

from pathlib import Path
from typing import Mapping

from tools.update_client import (
    BUNDLE_ASSET_NAME,
    MANIFEST_ASSET_NAME,
    UpdateError,
    UpdateOffer,
    Version,
    _asset_map,
    fetch_releases,
    parse_version,
    read_installed_version,
    select_update,
)


def _newer_releases(
    releases: list[dict[str, object]],
    installed: Version,
) -> list[tuple[Version, Mapping[str, object]]]:
    candidates: list[tuple[Version, Mapping[str, object]]] = []
    for release in releases:
        if bool(release.get("draft")):
            continue
        version = parse_version(str(release.get("tag_name") or ""))
        if version is None or version <= installed:
            continue
        if bool(release.get("prerelease")) and not installed.is_prerelease:
            continue
        candidates.append((version, release))
    return sorted(candidates, key=lambda item: item[0], reverse=True)


def check_for_update(
    project_root: Path,
    token: str | None = None,
) -> UpdateOffer | None:
    """Return a complete Host update or expose a broken newer release.

    Older clients silently skipped a release when either updater asset was
    missing and then displayed "already up to date."  That masks a publication
    failure.  The latest newer release now wins only when both assets exist;
    otherwise the UI reports the exact missing files.
    """

    installed = read_installed_version(project_root)
    releases = fetch_releases(token)
    offer = select_update(releases, installed)
    newer = _newer_releases(releases, installed)
    if not newer:
        return offer

    latest_version, latest_release = newer[0]
    if offer is not None and offer.version >= latest_version:
        return offer

    assets = _asset_map(latest_release)
    missing = [
        name
        for name in (MANIFEST_ASSET_NAME, BUNDLE_ASSET_NAME)
        if name not in assets or assets[name].size <= 0
    ]
    if missing:
        tag = str(latest_release.get("tag_name") or latest_version.text)
        raise UpdateError(
            f"DjGoo {latest_version.text} exists, but GitHub did not finish "
            f"publishing its Host updater files: {', '.join(missing)}. "
            f"Release {tag} is incomplete and cannot be installed safely."
        )
    return offer
