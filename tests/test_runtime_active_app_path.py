from __future__ import annotations

from tools.prepare_runtime_layers import ACTIVE_APP_PTH_LINE


def test_active_app_pth_is_valid_site_directive() -> None:
    assert ACTIVE_APP_PTH_LINE.startswith("import ")
    assert "DJGOO_APP_ROOT" in ACTIVE_APP_PTH_LINE
    assert "DJGOO_HOME" in ACTIVE_APP_PTH_LINE
    assert "'runtime','speech','Lib','site-packages'" in ACTIVE_APP_PTH_LINE
    assert "sys.path.insert(0" in ACTIVE_APP_PTH_LINE
    compile(ACTIVE_APP_PTH_LINE, "djgoo-root.pth", "exec")
