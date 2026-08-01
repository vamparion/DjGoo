from __future__ import annotations

from tools.update_client import parse_version
from tools.voice_update_client import select_voice_update


def test_recipient_updater_requires_recipient_assets() -> None:
    installed = parse_version("0.3.0-alpha.12")
    assert installed is not None
    releases = [
        {
            "tag_name": "v0.3.0-alpha.13",
            "name": "DjGoo 0.3.0-alpha.13",
            "prerelease": True,
            "draft": False,
            "assets": [
                {"name": "DjGoo-Host-update.json", "url": "https://example/host-json", "size": 1},
                {"name": "DjGoo-Host-update.zip", "url": "https://example/host-zip", "size": 1},
            ],
        },
        {
            "tag_name": "v0.3.0-alpha.14",
            "name": "DjGoo 0.3.0-alpha.14",
            "prerelease": True,
            "draft": False,
            "assets": [
                {"name": "DjGoo-Voice-update.json", "url": "https://example/voice-json", "size": 10},
                {"name": "DjGoo-Voice-update.zip", "url": "https://example/voice-zip", "size": 20},
            ],
        },
    ]
    offer = select_voice_update(releases, installed)
    assert offer is not None
    assert offer.version.text == "0.3.0-alpha.14"
    assert offer.manifest_asset.name == "DjGoo-Voice-update.json"
