from __future__ import annotations

import sys
from pathlib import Path

from tools.runtime_layers import activate_host_webrtc_layer


def test_activate_host_webrtc_layer_from_trusted_package_root(
    tmp_path: Path, monkeypatch
) -> None:
    site_packages = tmp_path / "runtime" / "webrtc" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    monkeypatch.setenv("DJGOO_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "path", [item for item in sys.path if item != str(site_packages)])

    activated = activate_host_webrtc_layer()

    assert activated == site_packages.resolve()
    assert sys.path[0] == str(site_packages.resolve())


def test_missing_webrtc_layer_does_not_modify_import_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DJGOO_HOME", str(tmp_path))
    before = list(sys.path)

    assert activate_host_webrtc_layer() is None
    assert sys.path == before
