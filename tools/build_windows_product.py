from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from tools.build_app_layer import build as build_app_layer


ROOT = Path(__file__).resolve().parents[1]
SOLUTION = ROOT / "src" / "windows" / "DjGoo.Product" / "DjGoo.Product.sln"


def directory_identity(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    files = (item for item in root.rglob("*") if item.is_file())
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix().lower()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        length = path.stat().st_size
        digest.update(length.to_bytes(8, "little"))
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        size += length
    if size <= 0:
        raise RuntimeError(f"Layer is empty: {root}")
    return digest.hexdigest(), size


def copy_layer(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def publish(project: str, output: Path) -> Path:
    project_path = ROOT / "src" / "windows" / "DjGoo.Product" / project / f"{project}.csproj"
    subprocess.run(
        [
            "dotnet", "publish", str(project_path), "-c", "Release", "-r", "win-x64",
            "--self-contained", "true", "-p:PublishSingleFile=true", "-p:DebugType=None",
            "-o", str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    executables = list(output.glob("*.exe"))
    if len(executables) != 1:
        raise RuntimeError(f"Expected one executable from {project}: {executables}")
    return executables[0]


def layer(generation: str, version: str, location: str, artifact: str, root: Path, *, optional: bool = False) -> dict[str, object]:
    digest, size = directory_identity(root)
    return {
        "generation": generation,
        "version": version,
        "sha256": digest,
        "size": size,
        "location": location.replace("\\", "/"),
        "artifact": artifact,
        "optional": optional,
    }


def build(args: argparse.Namespace) -> Path:
    output = args.output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    app_location = f"app/{args.version}"
    python_location = f"layers/python-red/{args.python_generation}"
    java_location = f"layers/java/{args.java_generation}"
    lavalink_location = f"layers/lavalink/{args.lavalink_generation}"
    webrtc_location = f"layers/webrtc/{args.webrtc_generation}"

    app = build_app_layer(output / app_location, "host", args.version)
    python = output / python_location
    java = output / java_location
    lavalink = output / lavalink_location
    webrtc = output / webrtc_location
    copy_layer(args.python.resolve(), python)
    if args.voice_python:
        voice_site = args.voice_python.resolve() / "Lib" / "site-packages"
        if not voice_site.is_dir():
            raise FileNotFoundError(voice_site)
        shutil.copytree(voice_site, python / "Lib" / "site-packages", dirs_exist_ok=True)
    copy_layer(args.java.resolve(), java)
    copy_layer(args.webrtc.resolve(), webrtc)
    lavalink.mkdir(parents=True)
    shutil.copy2(args.lavalink.resolve(), lavalink / "Lavalink.jar")
    shutil.copy2(ROOT / "config" / "lavalink.application.yml", lavalink / "application.yml")
    plugins = lavalink / "plugins"
    plugins.mkdir()
    shutil.copy2(args.youtube_plugin.resolve(), plugins / args.youtube_plugin.name)

    native = output / ".native"
    shutil.copy2(publish("DjGoo.Host", native / "host"), output / "DjGoo.Host.exe")
    shutil.copy2(publish("DjGoo.ControlCenter", native / "control"), output / "DjGoo.exe")
    shutil.copy2(publish("DjGoo.Updater", native / "updater"), output / "DjGoo.Updater.exe")
    shutil.copy2(ROOT / "config" / "release-public-key.pem", output / "release-public-key.pem")
    shutil.rmtree(native)

    manifest = {
        "schema": 1,
        "application": layer(args.version, args.version, app_location, f"djgoo-app-{args.version}.zip", app),
        "python_red": layer(args.python_generation, "3.11.9-red-3.5.24", python_location, f"python-red-{args.python_generation}.zip", python),
        "java": layer(args.java_generation, "17.0.17", java_location, f"java-{args.java_generation}.zip", java),
        "lavalink": layer(args.lavalink_generation, "red-pinned", lavalink_location, f"lavalink-{args.lavalink_generation}.zip", lavalink),
        "webrtc": layer(args.webrtc_generation, "1", webrtc_location, f"webrtc-{args.webrtc_generation}.zip", webrtc),
        "speech": None,
    }
    (output / "product-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "current.json").write_text(
        json.dumps({"schema": 1, "version": args.version, "path": app_location}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "VERSION").write_text(args.version + "\n", encoding="ascii")
    print(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the self-contained DjGoo Windows product payload.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--voice-python", type=Path)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--webrtc", type=Path, required=True)
    parser.add_argument("--lavalink", type=Path, required=True)
    parser.add_argument("--youtube-plugin", type=Path, required=True)
    parser.add_argument("--python-generation", default="bot-745f76594ec2f6df182a")
    parser.add_argument("--java-generation", default="jre-eefd194014ddc7956880")
    parser.add_argument("--webrtc-generation", default="webrtc-4a7f0fabd7ec821fc1f3")
    parser.add_argument("--lavalink-generation", default="red-pinned-v1")
    build(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
