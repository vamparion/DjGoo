from __future__ import annotations

import json
from pathlib import Path

from tools.update_client import (
    BUNDLE_ASSET_NAME,
    MANIFEST_ASSET_NAME,
    parse_version,
    read_installed_version,
    select_update,
)


def _release(tag: str, *, prerelease: bool = True, assets: bool = True) -> dict[str, object]:
    release_assets = []
    if assets:
        release_assets = [
            {"name": MANIFEST_ASSET_NAME, "url": "https://api.example/manifest", "size": 100},
            {"name": BUNDLE_ASSET_NAME, "url": "https://api.example/bundle", "size": 200},
        ]
    return {
        "tag_name": tag,
        "name": tag,
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-08-01T00:00:00Z",
        "assets": release_assets,
    }


def test_semantic_version_ordering() -> None:
    values = [
        parse_version("v1.2.3-alpha.1"),
        parse_version("1.2.3-alpha.2"),
        parse_version("1.2.3-beta.1"),
        parse_version("1.2.3-rc.1"),
        parse_version("1.2.3"),
        parse_version("1.2.4-alpha.1"),
    ]
    assert all(value is not None for value in values)
    assert values == sorted(values)
    assert parse_version("not-a-version") is None


def test_select_update_requires_both_small_update_assets() -> None:
    installed = parse_version("0.3.0-alpha.1")
    assert installed is not None
    offer = select_update(
        [
            _release("v0.3.0-alpha.2", assets=False),
            _release("v0.3.0-alpha.3"),
            _release("v0.3.0-alpha.4", assets=False),
        ],
        installed,
    )
    assert offer is not None
    assert offer.tag == "v0.3.0-alpha.3"
    assert offer.bundle_asset.name == BUNDLE_ASSET_NAME


def test_stable_install_does_not_follow_prereleases() -> None:
    installed = parse_version("1.0.0")
    assert installed is not None
    offer = select_update(
        [
            _release("v1.1.0-alpha.1", prerelease=True),
            _release("v1.0.1", prerelease=False),
        ],
        installed,
    )
    assert offer is not None
    assert offer.tag == "v1.0.1"


def test_read_installed_version_prefers_installed_version_file(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "installed-version.json").write_text(
        json.dumps({"version": "0.4.0-beta.2"}),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": "0.1.0"}),
        encoding="utf-8",
    )
    assert read_installed_version(tmp_path).text == "0.4.0-beta.2"
