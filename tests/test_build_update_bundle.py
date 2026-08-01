from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from tools.build_update_bundle import build_update_bundle


def test_update_bundle_excludes_large_runtimes_and_user_state(tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / "tools").mkdir(parents=True)
    audio_dir = package / "data" / "discordbot" / "cogs" / "Audio"
    audio_dir.mkdir(parents=True)
    (package / "logs").mkdir(parents=True)
    (package / "config").mkdir(parents=True)
    (package / "runtime" / "java" / "bin").mkdir(parents=True)
    pip_dir = package / "runtime" / "python" / "Lib" / "site-packages" / "pip"
    pip_info = package / "runtime" / "python" / "Lib" / "site-packages" / "pip-26.0.dist-info"
    pip_dir.mkdir(parents=True)
    pip_info.mkdir(parents=True)

    (package / "DjGoo.exe").write_bytes(b"launcher")
    (package / "tools" / "worker.py").write_text("print('updated')", encoding="utf-8")
    (package / "data" / "history.json").write_text("private history", encoding="utf-8")
    (package / "data" / "installed-version.json").write_text(
        json.dumps({"version": "0.3.0-alpha.10"}),
        encoding="utf-8",
    )
    (package / "data" / "lavalink-contract.json").write_text(
        json.dumps({"lavalink_version": "3.7.13+red.5"}),
        encoding="utf-8",
    )
    (audio_dir / "Lavalink.jar").write_bytes(b"red-pinned-lavalink")
    (audio_dir / "application.yml").write_text(
        'server:\n  address: "::1"\n  port: 2333\n',
        encoding="utf-8",
    )
    (package / "logs" / "bot.log").write_text("private log", encoding="utf-8")
    (package / "config" / "secrets.json").write_text("secret", encoding="utf-8")
    (package / "config" / "secrets.example.json").write_text("example", encoding="utf-8")
    (package / "runtime" / "java" / "bin" / "java.exe").write_bytes(b"large-java")
    (pip_dir / "__init__.py").write_text("__version__='26.0'", encoding="utf-8")
    (pip_info / "METADATA").write_text("Name: pip", encoding="utf-8")

    output_zip = tmp_path / "DjGoo-Host-update.zip"
    output_manifest = tmp_path / "DjGoo-Host-update.json"
    manifest = build_update_bundle(package, output_zip, output_manifest, "0.3.0-alpha.10")

    with zipfile.ZipFile(output_zip) as archive:
        names = set(archive.namelist())
        assert "DjGoo.exe" in names
        assert "tools/worker.py" in names
        assert "config/secrets.example.json" in names
        assert "data/installed-version.json" in names
        assert "data/lavalink-contract.json" in names
        assert "data/discordbot/cogs/Audio/Lavalink.jar" in names
        assert "data/discordbot/cogs/Audio/application.yml" in names
        assert "runtime/python/Lib/site-packages/pip/__init__.py" in names
        assert "runtime/python/Lib/site-packages/pip-26.0.dist-info/METADATA" in names
        assert "config/secrets.json" not in names
        assert "data/history.json" not in names
        assert not any(name.startswith(("logs/", "runtime/java/")) for name in names)

    disk_manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
    assert disk_manifest == manifest
    assert manifest["release_tag"] == "v0.3.0-alpha.10"
    assert manifest["runtime_generation"] == 3
    assert manifest["bundle_size"] == output_zip.stat().st_size
    assert manifest["bundle_sha256"] == hashlib.sha256(output_zip.read_bytes()).hexdigest()
    listed = {entry["path"]: entry for entry in manifest["files"]}
    assert set(listed) == names
    with zipfile.ZipFile(output_zip) as archive:
        for name in names:
            data = archive.read(name)
            assert listed[name]["size"] == len(data)
            assert listed[name]["sha256"] == hashlib.sha256(data).hexdigest()
