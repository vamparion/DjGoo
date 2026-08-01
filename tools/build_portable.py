from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


# GitHub Actions invokes this file by path, so add the repository root before
# importing sibling modules through the ``tools`` package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.red_lavalink_contract import (
    ensure_red_lavalink_contract,
    write_red_application_yml,
)


COPY_DIRECTORIES = ("config", "control_panel_dist", "launcher", "local_cogs", "tools", "voice")
COPY_FILES = (
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements-bot.txt",
    "requirements-voice.txt",
    "pyproject.toml",
)
EXCLUDED_SUFFIXES = {".ps1", ".vbs", ".pyc"}
EXCLUDED_NAMES = {"__pycache__", ".git", ".github", ".venv", ".voice-venv", "node_modules"}
RUNTIME_GENERATION = 3


def ignore_copy(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        if name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
            ignored.add(name)
    return ignored


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore_copy)


def build_launcher(output: Path) -> Path:
    dist = output.parent / "launcher-dist"
    build = output.parent / "launcher-build"
    spec = output.parent / "launcher-spec"
    for path in (dist, build, spec):
        shutil.rmtree(path, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "DjGoo",
        "--distpath",
        str(dist),
        "--workpath",
        str(build),
        "--specpath",
        str(spec),
        str(PROJECT_ROOT / "launcher" / "djgoo_launcher.py"),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    launcher = dist / "DjGoo.exe"
    if not launcher.exists():
        raise FileNotFoundError("PyInstaller did not produce DjGoo.exe")
    shutil.copy2(launcher, output / "DjGoo.exe")
    return output / "DjGoo.exe"


def install_portable_supervisor(output: Path) -> None:
    tools = output / "tools"
    source_core = tools / "djgoo_stack.py"
    adapter = tools / "djgoo_portable_stack.py"
    portable_core = tools / "djgoo_stack_core.py"
    if not source_core.exists() or not adapter.exists():
        raise FileNotFoundError("Portable supervisor sources are incomplete")
    shutil.copy2(source_core, portable_core)
    shutil.copy2(adapter, source_core)


def write_installed_version(output: Path, version: str) -> None:
    payload = {
        "schema": 1,
        "version": str(version).strip().lstrip("v"),
        "release_tag": f"v{str(version).strip().lstrip('v')}",
        "runtime_generation": RUNTIME_GENERATION,
        "installed_at": time.time(),
    }
    path = output / "data" / "installed-version.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_lavalink_contract(output: Path, contract: dict[str, object]) -> None:
    path = output / "data" / "lavalink-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "red_package": "Red-DiscordBot==3.5.24",
        "connection_mode": "external",
        "client_host": "[::1]",
        "bind_host": "::1",
        "port": 2333,
        **contract,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_manifest(output: Path, version: str) -> None:
    files: list[dict[str, object]] = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "size": path.stat().st_size,
                "sha256": digest,
            }
        )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "version": str(version).strip().lstrip("v"),
                "runtime_generation": RUNTIME_GENERATION,
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build(output: Path, runtime_python: Path, runtime_java: Path, lavalink_jar: Path, version: str) -> None:
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)

    for directory in COPY_DIRECTORIES:
        copy_tree(PROJECT_ROOT / directory, output / directory)
    for filename in COPY_FILES:
        source = PROJECT_ROOT / filename
        if source.exists():
            shutil.copy2(source, output / filename)

    install_portable_supervisor(output)
    copy_tree(runtime_python, output / "runtime" / "python")
    copy_tree(runtime_java, output / "runtime" / "java")

    selected_jar = output.parent / "Lavalink-red-pinned.jar"
    selected_jar.unlink(missing_ok=True)
    runtime_python_executable = output / "runtime" / "python" / "python.exe"
    if not runtime_python_executable.exists():
        runtime_python_executable = output / "runtime" / "python" / "python"
    contract = ensure_red_lavalink_contract(
        runtime_python=runtime_python_executable,
        runtime_java=output / "runtime" / "java",
        candidate_jar=lavalink_jar,
        output_jar=selected_jar,
    )

    lavalink_dir = output / "data" / "discordbot" / "cogs" / "Audio"
    lavalink_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected_jar, lavalink_dir / "Lavalink.jar")
    write_red_application_yml(
        runtime_python=runtime_python_executable,
        output=lavalink_dir / "application.yml",
        bind_host="::1",
        port=2333,
        password="youshallnotpass",
    )
    for relative in (
        "config",
        "data",
        "data/models",
        "data/health",
        "data/pids",
        "data/updates",
        "data/update-backups",
        "logs",
        "licenses",
    ):
        (output / relative).mkdir(parents=True, exist_ok=True)

    write_lavalink_contract(output, contract)
    build_launcher(output)
    write_installed_version(output, version)
    write_manifest(output, version)

    forbidden = [path for path in output.rglob("*") if path.suffix.lower() in {".ps1", ".vbs"}]
    if forbidden:
        raise RuntimeError(f"Portable package contains forbidden scripts: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a portable DjGoo host directory.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-java", type=Path, required=True)
    parser.add_argument("--lavalink-jar", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(
        args.output.resolve(),
        args.runtime_python.resolve(),
        args.runtime_java.resolve(),
        args.lavalink_jar.resolve(),
        args.version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
