from __future__ import annotations

import pytest

from tools.update_client import ReleaseAsset, UpdateError, UpdateOffer, parse_version
from tools.voice_update_client import select_voice_update, validate_voice_manifest


def _offer() -> UpdateOffer:
    version = parse_version("0.3.0-alpha.13")
    assert version is not None
    return UpdateOffer(
        tag="v0.3.0-alpha.13",
        version=version,
        release_name="DjGoo 0.3.0-alpha.13",
        published_at="2026-08-01T00:00:00Z",
        manifest_asset=ReleaseAsset(
            "DjGoo-Voice-update.json",
            "https://example/manifest",
            1,
        ),
        bundle_asset=ReleaseAsset(
            "DjGoo-Voice-update.zip",
            "https://example/bundle",
            1,
        ),
    )


def _manifest(*, files=None, runtime_generation: int = 3):
    return {
        "schema": 1,
        "product": "DjGoo Voice",
        "version": "0.3.0-alpha.13",
        "release_tag": "v0.3.0-alpha.13",
        "bundle_asset": "DjGoo-Voice-update.zip",
        "bundle_sha256": "0" * 64,
        "bundle_size": 1,
        "runtime_generation": runtime_generation,
        "requires_full_install": False,
        "files": files or [{"path": "voice/input_binding.py"}],
        "deletes": [],
    }


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
                {
                    "name": "DjGoo-Host-update.json",
                    "url": "https://example/host-json",
                    "size": 1,
                },
                {
                    "name": "DjGoo-Host-update.zip",
                    "url": "https://example/host-zip",
                    "size": 1,
                },
            ],
        },
        {
            "tag_name": "v0.3.0-alpha.14",
            "name": "DjGoo 0.3.0-alpha.14",
            "prerelease": True,
            "draft": False,
            "assets": [
                {
                    "name": "DjGoo-Voice-update.json",
                    "url": "https://example/voice-json",
                    "size": 10,
                },
                {
                    "name": "DjGoo-Voice-update.zip",
                    "url": "https://example/voice-zip",
                    "size": 20,
                },
            ],
        },
    ]
    offer = select_voice_update(releases, installed)
    assert offer is not None
    assert offer.version.text == "0.3.0-alpha.14"
    assert offer.manifest_asset.name == "DjGoo-Voice-update.json"


def test_recipient_manifest_accepts_matching_runtime_generation() -> None:
    payload = _manifest()
    assert validate_voice_manifest(
        payload,
        _offer(),
        installed_runtime_generation=3,
    ) == payload


def test_recipient_manifest_rejects_runtime_generation_change() -> None:
    with pytest.raises(UpdateError, match="full package"):
        validate_voice_manifest(
            _manifest(runtime_generation=4),
            _offer(),
            installed_runtime_generation=3,
        )


@pytest.mark.parametrize(
    "protected_path",
    [
        "runtime/python/python.exe",
        "data/voice-remote-credential.json",
        "data/models/model.bin",
        "config/voice-remote.json",
        "config/update-auth.json",
        "logs/voice-remote.out.log",
    ],
)
def test_recipient_manifest_rejects_protected_local_state(
    protected_path: str,
) -> None:
    with pytest.raises(UpdateError, match="protected local state"):
        validate_voice_manifest(
            _manifest(files=[{"path": protected_path}]),
            _offer(),
            installed_runtime_generation=3,
        )
