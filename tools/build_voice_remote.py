from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_portable import copy_tree, write_installed_version, write_manifest


UPDATE_TOOL_FILES = (
    "__init__.py",
    "update_auth.py",
    "update_client.py",
    "voice_update_client.py",
    "apply_update.py",
    "apply_voice_update.py",
    "portable_environment.py",
)


def build_launcher(output: Path) -> Path:
    dist = output.parent / "voice-launcher-dist"
    build = output.parent / "voice-launcher-build"
    spec = output.parent / "voice-launcher-spec"
    for path in (dist, build, spec):
        shutil.rmtree(path, ignore_errors=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "DjGoo Voice",
            "--distpath",
            str(dist),
            "--workpath",
            str(build),
            "--specpath",
            str(spec),
            str(PROJECT_ROOT / "launcher" / "djgoo_voice_control_center.py"),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    launcher = dist / "DjGoo Voice.exe"
    if not launcher.exists():
        raise FileNotFoundError("PyInstaller did not produce DjGoo Voice.exe")
    destination = output / "DjGoo Voice.exe"
    shutil.copy2(launcher, destination)
    return destination


def build(output: Path, runtime_python: Path, version: str) -> None:
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)

    copy_tree(PROJECT_ROOT / "voice", output / "voice")
    copy_tree(PROJECT_ROOT / "launcher", output / "source" / "launcher")
    tools_output = output / "tools"
    tools_output.mkdir(parents=True, exist_ok=True)
    for filename in UPDATE_TOOL_FILES:
        source = PROJECT_ROOT / "tools" / filename
        if source.exists():
            shutil.copy2(source, tools_output / filename)
    for filename in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "requirements-voice.txt"):
        source = PROJECT_ROOT / filename
        if source.exists():
            shutil.copy2(source, output / filename)

    corrections = PROJECT_ROOT / "config" / "voice-corrections.example.json"
    config = output / "config"
    config.mkdir(parents=True, exist_ok=True)
    if corrections.exists():
        shutil.copy2(corrections, config / corrections.name)
    (config / "voice-remote.example.json").write_text(
        "{\n"
        "  \"voice\": {\n"
        "    \"model\": \"distil-large-v3\",\n"
        "    \"device\": \"cpu\",\n"
        "    \"compute_type\": \"int8\",\n"
        "    \"hotkey\": \"F12\",\n"
        "    \"input_device\": null,\n"
        "    \"feedback_beeps\": true\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    copy_tree(runtime_python, output / "runtime" / "python")
    for relative in ("data", "data/models", "data/updates", "data/update-backups", "logs"):
        (output / relative).mkdir(parents=True, exist_ok=True)
    build_launcher(output)
    write_installed_version(output, version)
    write_manifest(output, version)

    forbidden = [path for path in output.rglob("*") if path.suffix.lower() in {".ps1", ".vbs"}]
    if forbidden:
        raise RuntimeError(f"Voice Remote package contains forbidden scripts: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable DjGoo Voice Remote package.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.runtime_python.resolve(), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
