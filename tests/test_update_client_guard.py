from __future__ import annotations

from pathlib import Path

import pytest

from tools import update_client_guard
from tools.update_client import UpdateError, parse_version


def release(version: str, assets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "tag_name": f"v{version}",
        "name": f"DjGoo {version}",
        "draft": False,
        "prerelease": True,
        "published_at": "2026-08-02T00:00:00Z",
        "assets": assets,
    }


def asset(name: str, size: int = 10) -> dict[str, object]:
    return {
        "name": name,
        "url": f"https://api.github.test/assets/{name}",
        "size": size,
    }


def test_incomplete_newer_release_is_not_reported_as_up_to_date(monkeypatch) -> None:
    installed = parse_version("0.3.0-alpha.17")
    assert installed is not None
    monkeypatch.setattr(
        update_client_guard,
        "read_installed_version",
        lambda _root: installed,
    )
    monkeypatch.setattr(
        update_client_guard,
        "fetch_releases",
        lambda _token=None: [
            release(
                "0.3.0-alpha.18",
                [asset("DjGoo-Host-update.json")],
            )
        ],
    )

    with pytest.raises(UpdateError, match="DjGoo-Host-update.zip"):
        update_client_guard.check_for_update(Path("."))


def test_complete_newer_release_is_offered(monkeypatch) -> None:
    installed = parse_version("0.3.0-alpha.17")
    assert installed is not None
    monkeypatch.setattr(
        update_client_guard,
        "read_installed_version",
        lambda _root: installed,
    )
    monkeypatch.setattr(
        update_client_guard,
        "fetch_releases",
        lambda _token=None: [
            release(
                "0.3.0-alpha.19",
                [
                    asset("DjGoo-Host-update.json"),
                    asset("DjGoo-Host-update.zip"),
                ],
            )
        ],
    )

    offer = update_client_guard.check_for_update(Path("."))

    assert offer is not None
    assert offer.version.text == "0.3.0-alpha.19"
