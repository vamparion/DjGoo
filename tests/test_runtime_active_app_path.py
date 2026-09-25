from __future__ import annotations

from pathlib import Path

from tools.app_layout import resolve_java
from tools import djgoo_portable_stack_entry
from tools.prepare_runtime_layers import ACTIVE_APP_PTH_LINE


def test_active_app_pth_is_valid_site_directive() -> None:
    assert ACTIVE_APP_PTH_LINE.startswith("import ")
    assert "DJGOO_APP_ROOT" in ACTIVE_APP_PTH_LINE
    assert "DJGOO_HOME" in ACTIVE_APP_PTH_LINE
    assert "'runtime','speech','Lib','site-packages'" in ACTIVE_APP_PTH_LINE
    assert "'runtime','webrtc','Lib','site-packages'" in ACTIVE_APP_PTH_LINE
    assert "sys.path.insert(0" in ACTIVE_APP_PTH_LINE
    compile(ACTIVE_APP_PTH_LINE, "djgoo-root.pth", "exec")


def test_java_resolution_prefers_packaged_runtime(tmp_path: Path, monkeypatch) -> None:
    packaged = tmp_path / "runtime" / "java" / "bin" / "java.exe"
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes(b"java")
    monkeypatch.setattr("tools.app_layout.shutil.which", lambda *args, **kwargs: "C:/PATH/java.exe")

    assert resolve_java(tmp_path, {"DJGOO_JAVA": "C:/custom/java.exe"}) == packaged.resolve()


def test_java_resolution_supports_explicit_path(tmp_path: Path) -> None:
    configured = tmp_path / "jdk" / "bin" / "java.exe"
    configured.parent.mkdir(parents=True)
    configured.write_bytes(b"java")

    assert resolve_java(tmp_path, {"DJGOO_JAVA": str(configured)}) == configured.resolve()


def test_java_resolution_uses_path_for_source_checkout(tmp_path: Path, monkeypatch) -> None:
    discovered = tmp_path / "Program Files" / "Java" / "bin" / "java.exe"
    discovered.parent.mkdir(parents=True)
    discovered.write_bytes(b"java")
    calls: list[tuple[str, str | None]] = []

    def which(command: str, path: str | None = None) -> str | None:
        calls.append((command, path))
        return str(discovered) if command == "java.exe" else None

    monkeypatch.setattr("tools.app_layout.shutil.which", which)

    assert resolve_java(tmp_path, {"PATH": "jdk-bin"}) == discovered.resolve()
    assert calls == [("java.exe", "jdk-bin")]


def test_supervisor_entry_prioritizes_active_app_over_source_root() -> None:
    app_root = Path("C:/DjGoo/app/0.3.0-alpha.29")
    paths = ["C:/DjGoo", str(app_root), "C:/Python"]

    djgoo_portable_stack_entry.prioritize_app_root(app_root, paths)

    assert paths == [str(app_root), "C:/DjGoo", "C:/Python"]
