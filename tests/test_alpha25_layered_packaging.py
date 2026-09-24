from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from tools.app_layout import active_app_root, write_current
from tools.build_app_layer import build as build_app_layer
from tools.build_update_bundle import build_update_bundle
from tools.apply_update import apply_staged_update, extract_verified_bundle, validate_bundle
from tools.build_voice_update_bundle import build_voice_update_bundle
from tools.cleanup_legacy_layout import cleanup_legacy_layout


VERSION = "0.3.0-alpha.25"


def _write(path: Path, data: str | bytes = "test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _layered_host_root(tmp_path: Path, version: str = VERSION) -> Path:
    root = tmp_path / "host"
    app = root / "app" / version
    _write(root / "DjGoo.exe", b"thin-host")
    _write(root / "DjGoo Mini Player.exe", b"thin-mini")
    _write(root / "current.json", json.dumps({"schema": 1, "version": version, "path": f"app/{version}"}))
    _write(root / "data" / "installed-version.json", json.dumps({"version": version}))
    _write(app / "app-layer.json", json.dumps({"schema": 1, "version": version}))
    _write(app / "launcher" / "djgoo_layered_host.py")
    _write(app / "tools" / "apply_update.py")
    _write(root / "tools" / "apply_update.py")
    _write(root / "tools" / "complete_launcher_update.py")
    _write(root / "tools" / "djgoo_stack.py")
    _write(root / "runtime" / "python-bot" / "python.exe", b"runtime-must-not-ship")
    _write(root / "runtime" / "java" / "bin" / "java.exe", b"runtime-must-not-ship")
    _write(root / "runtime" / "webrtc" / "layer-manifest.json", "{}")
    _write(root / "runtime" / "webrtc" / "Lib" / "site-packages" / "aiortc" / "__init__.py")
    _write(root / "runtime" / "webrtc" / "Lib" / "site-packages" / "av" / "_core.pyd", b"native")
    _write(root / "runtime" / "webrtc" / "Lib" / "site-packages" / "pylibsrtp" / "_binding.pyd", b"native")
    _write(root / "config" / "secrets.json", "private")
    _write(root / "logs" / "session.log", "private")
    return root


def _layered_voice_root(tmp_path: Path, version: str = VERSION) -> Path:
    root = tmp_path / "voice"
    app = root / "app" / version
    _write(root / "DjGoo Voice.exe", b"thin-voice")
    _write(root / "current.json", json.dumps({"schema": 1, "version": version, "path": f"app/{version}"}))
    _write(root / "data" / "installed-version.json", json.dumps({"version": version}))
    _write(app / "app-layer.json", json.dumps({"schema": 1, "version": version}))
    _write(app / "launcher" / "djgoo_layered_voice.py")
    _write(app / "voice" / "djgoo_voice_remote_bound.py")
    _write(root / "tools" / "apply_voice_update.py")
    _write(root / "runtime" / "python-voice" / "python.exe", b"runtime-must-not-ship")
    _write(root / "runtime" / "speech" / "Lib" / "site-packages" / "faster_whisper" / "__init__.py")
    return root


def test_current_pointer_selects_versioned_app_and_falls_back(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    assert active_app_root(root) == root

    app = root / "app" / VERSION
    app.mkdir(parents=True)
    write_current(root, VERSION)
    assert active_app_root(root, require=True) == app

    (root / "current.json").write_text(
        json.dumps({"schema": 1, "version": VERSION, "path": "../escape"}),
        encoding="utf-8",
    )
    try:
        active_app_root(root)
    except Exception as exc:
        assert "escapes package root" in str(exc)
    else:
        raise AssertionError("unsafe current.json path was accepted")


def test_alpha25_host_update_contains_only_app_layer_and_migration_launchers(tmp_path: Path) -> None:
    root = _layered_host_root(tmp_path)
    bundle = tmp_path / "DjGoo-Host-update.zip"
    manifest_path = tmp_path / "DjGoo-Host-update.json"

    manifest = build_update_bundle(root, bundle, manifest_path, VERSION)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())

    assert manifest["runtime_generation"] == 4
    assert manifest["package_layout"] == "versioned-app-v1"
    assert manifest["launcher_update_deferred"] is True
    assert f"app/{VERSION}/app-layer.json" in names
    assert "current.json" in names
    assert "tools/pending_launchers/DjGoo.exe" in names
    assert "tools/pending_launchers/DjGoo Mini Player.exe" in names
    assert "runtime/webrtc/Lib/site-packages/aiortc/__init__.py" in names
    assert not any(name.startswith("runtime/python") or name.startswith("runtime/java") for name in names)
    assert "config/secrets.json" not in names
    assert not any(name.startswith("logs/") for name in names)


def test_future_host_update_replaces_unlocked_thin_launchers_directly(tmp_path: Path) -> None:
    version = "0.3.0-alpha.26"
    root = _layered_host_root(tmp_path, version)
    bundle = tmp_path / "DjGoo-Host-update.zip"
    manifest_path = tmp_path / "DjGoo-Host-update.json"

    manifest = build_update_bundle(root, bundle, manifest_path, version)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())

    assert manifest["launcher_update_deferred"] is False
    assert manifest["launcher_completion_mode"] == ""
    assert "DjGoo.exe" in names
    assert "DjGoo Mini Player.exe" in names
    assert not any(name.startswith("tools/pending_launchers/") for name in names)
    assert "runtime/webrtc/Lib/site-packages/aiortc/__init__.py" in names
    assert not any(name.startswith("runtime/python") or name.startswith("runtime/java") for name in names)


def test_layered_voice_update_never_contains_python_or_speech_runtime(tmp_path: Path) -> None:
    root = _layered_voice_root(tmp_path)
    bundle = tmp_path / "DjGoo-Voice-update.zip"
    manifest_path = tmp_path / "DjGoo-Voice-update.json"

    manifest = build_voice_update_bundle(root, bundle, manifest_path, VERSION)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())

    assert manifest["runtime_generation"] == 4
    assert manifest["package_layout"] == "versioned-app-v1"
    assert "DjGoo Voice.exe" in names
    assert f"app/{VERSION}/launcher/djgoo_layered_voice.py" in names
    assert f"app/{VERSION}/voice/djgoo_voice_remote_bound.py" in names
    assert not any(name.startswith("runtime/") for name in names)


def test_app_layer_excludes_runtime_state_and_keeps_public_source(tmp_path: Path) -> None:
    output = tmp_path / "app"
    build_app_layer(output, "voice", VERSION)

    assert (output / "launcher" / "djgoo_layered_voice.py").is_file()
    assert (output / "tools" / "app_layout.py").is_file()
    assert (output / "voice" / "connection_manager.py").is_file()
    assert (output / "app-layer.json").is_file()
    assert not (output / "data").exists()
    assert not (output / "logs").exists()
    assert not (output / "config" / "secrets.json").exists()


def test_host_app_layer_contains_supervisor_core_source(tmp_path: Path) -> None:
    output = tmp_path / "host-app"
    build_app_layer(output, "host", VERSION)

    assert (output / "tools" / "djgoo_stack.py").is_file()
    assert (output / "tools" / "djgoo_portable_stack.py").is_file()
    assert (output / "tools" / "djgoo_portable_stack_entry.py").is_file()


def test_thin_launcher_is_extraction_free() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "launcher" / "windows" / "DjGooThinLauncher.cs").read_text(
        encoding="utf-8"
    )

    assert "PyInstaller" not in source
    assert "_MEI" not in source
    assert "launcher.djgoo_layered_host" in source
    assert "launcher.djgoo_layered_voice" in source
    assert "launcher.djgoo_layered_mini" in source
    assert 'Path.Combine(root, "runtime", runtimeName' in source
    assert 'Directory.Exists(Path.Combine(root, ".git"))' in source
    assert 'Path.Combine(root, sourceRuntime, "Scripts", "pythonw.exe")' in source
    assert 'Path.Combine(root, "runtime", "webrtc", "Lib", "site-packages")' in source


def test_legacy_flat_sources_are_removed_once_but_runtime_is_preserved(tmp_path: Path) -> None:
    root = tmp_path / "package"
    app = root / "app" / VERSION
    app.mkdir(parents=True)
    write_current(root, VERSION)
    for directory in ("launcher", "voice", "local_cogs", "control_panel"):
        _write(root / directory / "old.py")
    _write(root / "runtime" / "python" / "python.exe", b"preserved")
    _write(root / "data" / "user.json", "preserved")

    removed = cleanup_legacy_layout(root)

    assert set(removed) == {"launcher", "voice", "local_cogs", "control_panel"}
    assert (root / "runtime" / "python" / "python.exe").is_file()
    assert (root / "data" / "user.json").is_file()
    assert cleanup_legacy_layout(root) == []


def test_alpha25_update_adds_webrtc_layer_and_preserves_user_state(tmp_path: Path) -> None:
    package = _layered_host_root(tmp_path / "release", "0.3.0-alpha.26")
    bundle = tmp_path / "update.zip"
    manifest_path = tmp_path / "update.json"
    manifest = build_update_bundle(package, bundle, manifest_path, "0.3.0-alpha.26")
    installed = _layered_host_root(tmp_path / "installed", VERSION)
    shutil.rmtree(installed / "runtime" / "webrtc", ignore_errors=True)
    _write(installed / "config" / "secrets.json", "paired-secret")
    _write(installed / "data" / "djgoo-pairing.db", b"paired-database")
    staging = tmp_path / "staging"
    expected = validate_bundle(bundle, manifest)
    extract_verified_bundle(bundle, staging, expected)
    apply_staged_update(installed, staging, manifest, tmp_path / "backup")

    installed_payload = json.loads(
        (installed / "data" / "installed-version.json").read_text(encoding="utf-8")
    )
    assert installed_payload["version"] == "0.3.0-alpha.26"
    assert (installed / "runtime" / "webrtc" / "Lib" / "site-packages" / "aiortc" / "__init__.py").is_file()
    assert (installed / "config" / "secrets.json").read_text() == "paired-secret"
    assert (installed / "data" / "djgoo-pairing.db").read_bytes() == b"paired-database"
