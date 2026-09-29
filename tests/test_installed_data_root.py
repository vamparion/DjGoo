from pathlib import Path

from tools.app_layout import mutable_data_root


def test_installed_components_use_separate_mutable_data_root(tmp_path: Path) -> None:
    program = tmp_path / "Programs" / "DjGoo"
    data = tmp_path / "DjGoo"

    assert mutable_data_root(program, {"DJGOO_DATA_ROOT": str(data)}) == data.resolve()


def test_developer_mode_keeps_supplied_root(tmp_path: Path) -> None:
    assert mutable_data_root(tmp_path, {}) == tmp_path.resolve()
