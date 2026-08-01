from __future__ import annotations

import json
from pathlib import Path

from tools.build_portable import ignore_copy, install_portable_supervisor, write_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_repository_contains_no_powershell_or_vbscript_files() -> None:
    forbidden = sorted(
        str(path.relative_to(REPOSITORY_ROOT))
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".ps1", ".vbs"}
        and ".git" not in path.parts
        and "build" not in path.parts
    )
    assert forbidden == []


def test_public_copy_excludes_shell_entrypoints_defensively(tmp_path: Path) -> None:
    names = ["Start-DjGoo.ps1", "helper.vbs", "module.py", "README.md", "__pycache__"]
    ignored = ignore_copy(str(tmp_path), names)
    assert ignored == {"Start-DjGoo.ps1", "helper.vbs", "__pycache__"}


def test_portable_supervisor_adapter_replaces_public_entrypoint(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "djgoo_stack.py").write_text("CORE = True\n", encoding="utf-8")
    (tools / "djgoo_portable_stack.py").write_text("PORTABLE = True\n", encoding="utf-8")

    install_portable_supervisor(tmp_path)

    assert (tools / "djgoo_stack_core.py").read_text(encoding="utf-8") == "CORE = True\n"
    assert (tools / "djgoo_stack.py").read_text(encoding="utf-8") == "PORTABLE = True\n"


def test_manifest_contains_file_hashes(tmp_path: Path) -> None:
    (tmp_path / "example.txt").write_text("DjGoo\n", encoding="utf-8")
    write_manifest(tmp_path, "1.2.3")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.2.3"
    assert manifest["files"][0]["path"] == "example.txt"
    assert len(manifest["files"][0]["sha256"]) == 64
