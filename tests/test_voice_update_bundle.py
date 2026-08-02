from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tools.build_voice_update_bundle import build_voice_update_bundle


def _write(root: Path, relative: str, content: bytes = b"x") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_recipient_update_bundle_preserves_runtime_credentials_and_settings(
    tmp_path: Path,
) -> None:
    package = tmp_path / "DjGoo-Voice-win-x64"
    _write(package, "DjGoo Voice.exe", b"voice-exe")
    _write(package, "manifest.json", b'{"version":"0.3.0-alpha.13"}')
    _write(package, "voice/input_binding.py")
    _write(package, "voice/djgoo_voice_remote_bound.py")
    _write(package, "source/launcher/djgoo_voice_control_center.py")
    _write(package, "tools/__init__.py", b"")
    _write(package, "tools/apply_voice_update.py")
    _write(package, "tools/voice_update_client.py")

    # These are installation-specific and must never enter an incremental bundle.
    _write(package, "runtime/python/python.exe", b"locked-runtime")
    _write(package, "data/voice-remote-credential.json", b"private-device-token")
    _write(package, "config/voice-remote.json", b'{"voice":{"hotkey":"MOUSE4"}}')
    _write(package, "config/update-auth.json", b"private-github-token")
    _write(package, "logs/voice-remote.out.log", b"private-log")

    output_zip = tmp_path / "DjGoo-Voice-update.zip"
    output_manifest = tmp_path / "DjGoo-Voice-update.json"
    manifest = build_voice_update_bundle(
        package,
        output_zip,
        output_manifest,
        "0.3.0-alpha.13",
    )

    assert manifest["product"] == "DjGoo Voice"
    assert manifest["bundle_asset"] == "DjGoo-Voice-update.zip"
    assert manifest["version"] == "0.3.0-alpha.13"

    with zipfile.ZipFile(output_zip) as archive:
        names = set(archive.namelist())
    assert "DjGoo Voice.exe" in names
    assert "voice/input_binding.py" in names
    assert "tools/apply_voice_update.py" in names
    assert not any(name.startswith("runtime/") for name in names)
    assert "data/voice-remote-credential.json" not in names
    assert "config/voice-remote.json" not in names
    assert "config/update-auth.json" not in names
    assert not any(name.startswith("logs/") for name in names)

    persisted = json.loads(output_manifest.read_text(encoding="utf-8"))
    assert persisted == manifest
