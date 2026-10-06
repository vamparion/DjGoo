from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools import speech_runtime
from tools.build_speech_runtime import (
    SpeechRuntimeBuildError,
    build,
    verify_bundle,
)


def test_built_speech_zip_matches_manifest_byte_for_byte(tmp_path: Path) -> None:
    layer = tmp_path / "speech-layer"
    site_packages = layer / "Lib" / "site-packages"
    faster_whisper = site_packages / "faster_whisper" / "__init__.py"
    sounddevice_data = site_packages / "sounddevice" / "_data" / "__init__.py"
    faster_whisper.parent.mkdir(parents=True)
    sounddevice_data.parent.mkdir(parents=True)
    faster_whisper.write_bytes(b"__version__ = 'test'\r\n")
    sounddevice_data.write_bytes(b"")
    output_zip = tmp_path / "DjGoo-SpeechRuntime-win-x64.zip"
    output_manifest = tmp_path / "DjGoo-SpeechRuntime.json"

    manifest = build(layer, output_zip, output_manifest, "0.3.0-alpha.29")

    assert json.loads(output_manifest.read_text(encoding="utf-8")) == manifest
    listed = {str(item["path"]): item for item in manifest["files"]}
    with zipfile.ZipFile(output_zip, "r") as archive:
        assert set(archive.namelist()) == set(listed)
        for name, metadata in listed.items():
            data = archive.read(name)
            assert len(data) == metadata["size"]
            assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    assert (
        listed["runtime/speech/Lib/site-packages/sounddevice/_data/__init__.py"]
        ["size"]
        == 0
    )


def test_speech_bundle_verifier_rejects_manifest_drift(tmp_path: Path) -> None:
    bundle = tmp_path / "speech.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("runtime/speech/file.py", b"archive bytes")
    manifest = {
        "files": [
            {
                "path": "runtime/speech/file.py",
                "size": len(b"different"),
                "sha256": hashlib.sha256(b"different").hexdigest(),
            }
        ]
    }

    with pytest.raises(SpeechRuntimeBuildError, match="size mismatch"):
        verify_bundle(bundle, manifest)


def test_speech_download_installs_zero_byte_files(tmp_path: Path, monkeypatch) -> None:
    layer = tmp_path / "speech-layer"
    site_packages = layer / "Lib" / "site-packages"
    (site_packages / "faster_whisper").mkdir(parents=True)
    (site_packages / "faster_whisper" / "__init__.py").write_bytes(b"")
    (site_packages / "ctranslate2.pyd").write_bytes(b"native")
    empty = site_packages / "sounddevice" / "_data" / "__init__.py"
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")
    bundle = tmp_path / speech_runtime.ZIP_NAME
    manifest_path = tmp_path / speech_runtime.MANIFEST_NAME
    build(layer, bundle, manifest_path, "0.3.0-alpha.29")
    assets = {
        speech_runtime.ZIP_NAME: {"name": speech_runtime.ZIP_NAME},
        speech_runtime.MANIFEST_NAME: {"name": speech_runtime.MANIFEST_NAME},
    }
    payloads = {
        speech_runtime.ZIP_NAME: bundle.read_bytes(),
        speech_runtime.MANIFEST_NAME: manifest_path.read_bytes(),
    }
    monkeypatch.setattr(speech_runtime, "_release_assets", lambda version, token: assets)
    monkeypatch.setattr(
        speech_runtime,
        "_asset_bytes",
        lambda asset, token: payloads[str(asset["name"])],
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "installed-version.json").write_text(
        json.dumps({"version": "0.3.0-alpha.29"}),
        encoding="utf-8",
    )

    installed = speech_runtime.install_speech_runtime(tmp_path, token="test")

    assert installed == tmp_path / "runtime" / "speech"
    assert (
        installed / "Lib" / "site-packages" / "sounddevice" / "_data" / "__init__.py"
    ).read_bytes() == b""


def test_production_speech_installer_refuses_source_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    with pytest.raises(speech_runtime.SpeechRuntimeError, match="Developer Mode"):
        speech_runtime.install_speech_runtime(tmp_path, token="test")
