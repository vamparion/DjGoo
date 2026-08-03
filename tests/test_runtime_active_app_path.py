from __future__ import annotations

import sys
from pathlib import Path

from tools.prepare_runtime_layers import ACTIVE_APP_PTH_LINE


def test_embedded_runtime_pth_prepends_active_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = tmp_path / "app" / "0.3.0-alpha.25"
    app.mkdir(parents=True)
    monkeypatch.setenv("DJGOO_APP_ROOT", str(app))
    original = list(sys.path)
    try:
        exec(ACTIVE_APP_PTH_LINE, {})
        assert Path(sys.path[0]).resolve() == app.resolve()
    finally:
        sys.path[:] = original


def test_embedded_runtime_pth_ignores_missing_active_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    missing = tmp_path / "app" / "missing"
    monkeypatch.setenv("DJGOO_APP_ROOT", str(missing))
    original = list(sys.path)
    try:
        exec(ACTIVE_APP_PTH_LINE, {})
        assert sys.path == original
    finally:
        sys.path[:] = original


def test_active_app_pth_is_valid_site_directive() -> None:
    assert ACTIVE_APP_PTH_LINE.startswith("import ")
    assert "DJGOO_APP_ROOT" in ACTIVE_APP_PTH_LINE
