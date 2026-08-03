from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from tools.app_layout import current_payload
from tools.red_lavalink_contract import (
    ensure_red_lavalink_contract,
    write_red_application_yml,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GENERATION = 4


class LayeredPackageError(RuntimeError):
    pass


def _copy_tree(source: Path | None, destination: Path) -> None:
    if source is None or not source.is_dir():
        raise LayeredPackageError(f"Required package layer is missing: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_installed_version(root: Path, version: str, product: str) -> None:
    path = root / "data" / "installed-version.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": version,
                "release_tag": f"v{version}",
                "runtime_generation": RUNTIME_GENERATION,
                "package_layout": "versioned-app-v1",
                "product": product,
                "installed_at": time.time(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_runtime_layout(root: Path, product: str, speech_included: bool) -> None:
    path = root / "runtime" / "runtime-layout.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "runtime_generation": RUNTIME_GENERATION,
                "product": product,
                "python": "python-voice" if product == "voice" else "python-bot",
                "java": product == "host",
                "speech": speech_included,
                "speech_optional_on_host": product == "host",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(root: Path, version: str, product: str) -> None:
    files: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "version": version,
                "product": product,
                "runtime_generation": RUNTIME_GENERATION,
                "package_layout": "versioned-app-v1",
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _copy_public_root_files(app_layer: Path, root: Path) -> None:
    for filename in (
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        source = app_layer / filename
        if source.is_file():
            shutil.copy2(source, root / filename)
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    source_config = app_layer / "config"
    for name in (
        "secrets.example.json",
        "voice-corrections.example.json",
        "voice-remote.example.json",
    ):
        source = source_config / name
        if source.is_file():
            shutil.copy2(source, config / name)


def _copy_root_bootstrap_tools(app_layer: Path, root: Path, product: str) -> None:
    source_tools = app_layer / "tools"
    destination = root / "tools"
    destination.mkdir(parents=True, exist_ok=True)
    if product == "host":
        names = (
            "apply_update.py",
            "complete_launcher_update.py",
            "app_layout.py",
            "portable_environment.py",
            "layered_stack_bootstrap.py",
        )
    else:
        names = (
            "apply_voice_update.py",
            "voice_update_client.py",
            "update_client.py",
            "update_auth.py",
            "app_layout.py",
            "portable_environment.py",
        )
    for name in names:
        source = source_tools / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    if product == "host":
        bootstrap = source_tools / "layered_stack_bootstrap.py"
        if bootstrap.is_file():
            shutil.copy2(bootstrap, destination / "djgoo_stack.py")


def _install_host_audio(
    root: Path,
    runtime_python: Path,
    runtime_java: Path,
    lavalink_jar: Path,
) -> None:
    selected = root.parent / "Lavalink-red-pinned.jar"
    selected.unlink(missing_ok=True)
    python = root / "runtime" / "python-bot" / "python.exe"
    if not python.is_file():
        raise LayeredPackageError("Layered Host runtime does not contain python.exe")
    contract = ensure_red_lavalink_contract(
        runtime_python=python,
        runtime_java=root / "runtime" / "java",
        candidate_jar=lavalink_jar,
        output_jar=selected,
    )
    audio = root / "data" / "discordbot" / "cogs" / "Audio"
    audio.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected, audio / "Lavalink.jar")
    write_red_application_yml(
        runtime_python=python,
        output=audio / "application.yml",
        bind_host="::1",
        port=2333,
        password="youshallnotpass",
    )
    (root / "data" / "lavalink-contract.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "red_package": "Red-DiscordBot==3.5.24",
                "connection_mode": "external",
                "client_host": "[::1]",
                "bind_host": "::1",
                "port": 2333,
                **contract,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build(
    *,
    output: Path,
    product: str,
    version: str,
    app_layer: Path,
    launchers: Path,
    runtime_python: Path,
    runtime_java: Path | None = None,
    lavalink_jar: Path | None = None,
    speech_layer: Path | None = None,
    include_host_speech: bool = False,
) -> Path:
    normalized_product = product.strip().lower()
    if normalized_product not in {"host", "voice"}:
        raise LayeredPackageError(f"Unsupported product: {product}")
    normalized_version = version.strip().lstrip("v")
    output = output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    app_destination = output / "app" / normalized_version
    _copy_tree(app_layer.resolve(), app_destination)
    (output / "current.json").write_text(
        json.dumps(current_payload(normalized_version), indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_public_root_files(app_layer, output)
    _copy_root_bootstrap_tools(app_layer, output, normalized_product)

    if normalized_product == "host":
        launcher_names = ("DjGoo.exe", "DjGoo Mini Player.exe")
        python_name = "python-bot"
    else:
        launcher_names = ("DjGoo Voice.exe",)
        python_name = "python-voice"
    for name in launcher_names:
        source = launchers / name
        if not source.is_file():
            raise LayeredPackageError(f"Thin launcher is missing: {source}")
        shutil.copy2(source, output / name)

    _copy_tree(runtime_python.resolve(), output / "runtime" / python_name)
    speech_included = normalized_product == "voice" or include_host_speech
    if speech_included:
        _copy_tree(speech_layer.resolve() if speech_layer else None, output / "runtime" / "speech")

    if normalized_product == "host":
        if runtime_java is None or lavalink_jar is None:
            raise LayeredPackageError("Host package requires Java runtime and Lavalink jar")
        _copy_tree(runtime_java.resolve(), output / "runtime" / "java")
        _install_host_audio(output, runtime_python, runtime_java, lavalink_jar.resolve())

    for relative in (
        "data",
        "data/models",
        "data/health",
        "data/pids",
        "data/updates",
        "data/update-backups",
        "logs",
        "licenses",
        ".localappdata",
    ):
        (output / relative).mkdir(parents=True, exist_ok=True)

    _write_installed_version(output, normalized_version, normalized_product)
    _write_runtime_layout(output, normalized_product, speech_included)
    _write_manifest(output, normalized_version, normalized_product)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble a layered DjGoo package.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product", choices=("host", "voice"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app-layer", type=Path, required=True)
    parser.add_argument("--launchers", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--runtime-java", type=Path)
    parser.add_argument("--lavalink-jar", type=Path)
    parser.add_argument("--speech-layer", type=Path)
    parser.add_argument("--include-host-speech", action="store_true")
    args = parser.parse_args()
    build(
        output=args.output,
        product=args.product,
        version=args.version,
        app_layer=args.app_layer,
        launchers=args.launchers,
        runtime_python=args.runtime_python,
        runtime_java=args.runtime_java,
        lavalink_jar=args.lavalink_jar,
        speech_layer=args.speech_layer,
        include_host_speech=args.include_host_speech,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
