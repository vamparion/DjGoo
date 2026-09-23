from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_APP_PTH_LINE = (
    "import os,sys; "
    "sys.path.insert(0,os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','speech','Lib','site-packages')) "
    "if os.path.isdir(os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','speech','Lib','site-packages')) else None; "
    "sys.path.insert(0,os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','webrtc','Lib','site-packages')) "
    "if os.path.isdir(os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','webrtc','Lib','site-packages')) else None; "
    "sys.path.insert(0,os.environ['DJGOO_APP_ROOT']) "
    "if os.path.isdir(os.environ.get('DJGOO_APP_ROOT','')) else None"
)


class RuntimeLayerError(RuntimeError):
    pass


def _digest(parts: list[bytes]) -> str:
    value = hashlib.sha256()
    for part in parts:
        value.update(part)
        value.update(b"\0")
    return value.hexdigest()[:20]


def _file_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise RuntimeLayerError(f"Runtime requirement file is missing: {path}")
    return path.read_bytes()


def _python_embed(cache: Path, version: str, expected_md5: str) -> Path:
    downloads = cache / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / f"python-{version}-embed-amd64.zip"
    if not archive.is_file():
        temporary = archive.with_suffix(".tmp")
        urllib.request.urlretrieve(
            f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
            temporary,
        )
        os.replace(temporary, archive)
    actual = hashlib.md5(archive.read_bytes()).hexdigest().lower()
    if actual != expected_md5.lower():
        archive.unlink(missing_ok=True)
        raise RuntimeLayerError(
            f"Embedded Python checksum mismatch: expected {expected_md5}, got {actual}"
        )
    return archive


def _first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _install_tk_runtime(destination: Path) -> None:
    """Add the Tcl/Tk slice omitted by the Windows embeddable ZIP.

    PyInstaller previously carried this dependency inside each GUI executable.
    Thin launchers run the control centers through the shared runtime, so both
    Host and Voice Python layers need the standard ``tkinter`` package, its
    native extension, Tcl/Tk DLLs, and script libraries.
    """

    base = Path(sys.base_prefix).resolve()
    tkinter_source = base / "Lib" / "tkinter"
    tcl_source = base / "tcl"
    if not tkinter_source.is_dir() or not tcl_source.is_dir():
        raise RuntimeLayerError(
            f"Build Python does not contain its Tcl/Tk standard-library slice: {base}"
        )

    shutil.copytree(
        tkinter_source,
        destination / "Lib" / "tkinter",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        tcl_source,
        destination / "tcl",
        dirs_exist_ok=True,
    )

    native_files = ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll")
    for filename in native_files:
        source = _first_existing(
            [
                base / "DLLs" / filename,
                base / filename,
            ]
        )
        if source is None:
            raise RuntimeLayerError(
                f"Build Python Tcl/Tk native file is missing: {filename}"
            )
        # Embeddable Python loads extension modules and dependent DLLs from the
        # executable directory, matching the layout of its other .pyd files.
        shutil.copy2(source, destination / filename)


def _extract_python(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)
    site_packages = destination / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    pth = next(destination.glob("python*._pth"), None)
    if pth is None:
        raise RuntimeLayerError("Embedded Python did not contain a python*._pth file")
    pth.write_text(
        "python311.zip\n.\nLib\nLib/site-packages\nimport site\n",
        encoding="ascii",
    )
    # The embeddable distribution's ._pth mode intentionally ignores
    # PYTHONPATH. Add the mutable package root for bootstrap modules, then use
    # an executable .pth line to add the optional shared speech layer and put
    # the active immutable app layer first. Thin launchers set DJGOO_HOME and
    # DJGOO_APP_ROOT from their package location and current.json.
    (site_packages / "djgoo-root.pth").write_text(
        "../../../..\n" + ACTIVE_APP_PTH_LINE + "\n",
        encoding="ascii",
    )
    _install_tk_runtime(destination)


def _pip_install(target: Path, requirements: Path, *, no_deps: bool = False) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--target",
        str(target),
        "--requirement",
        str(requirements),
    ]
    if no_deps:
        command.insert(-2, "--no-deps")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def _atomic_cache(directory: Path, builder) -> Path:
    marker = directory / "layer-manifest.json"
    if marker.is_file():
        return directory
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=directory.name + "-", dir=directory.parent)
    )
    try:
        builder(temporary)
        (temporary / "layer-manifest.json").write_text(
            json.dumps({"schema": 1, "key": directory.name}, indent=2) + "\n",
            encoding="utf-8",
        )
        if directory.exists():
            shutil.rmtree(directory)
        os.replace(temporary, directory)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return directory


def prepare(
    cache_root: Path,
    python_version: str,
    python_embed_md5: str,
) -> dict[str, str]:
    cache_root = cache_root.resolve()
    archive = _python_embed(cache_root, python_version, python_embed_md5)
    bot_requirements = PROJECT_ROOT / "requirements-bot.txt"
    voice_requirements = PROJECT_ROOT / "requirements-voice-base.txt"
    speech_requirements = PROJECT_ROOT / "requirements-speech.txt"
    webrtc_requirements = PROJECT_ROOT / "requirements-webrtc.txt"

    # v5 adds the optional Host WebRTC layer under DJGOO_HOME to sys.path.
    # Windows embeddable Python ignores PYTHONPATH in ._pth mode, so both the
    # active app and speech paths must be installed through site processing.
    bot_key = _digest(
        [
            b"python-bot-v5-tk-active-app-speech-webrtc",
            python_version.encode(),
            _file_bytes(bot_requirements),
        ]
    )
    voice_key = _digest(
        [
            b"python-voice-v5-tk-active-app-speech-webrtc",
            python_version.encode(),
            _file_bytes(voice_requirements),
        ]
    )
    speech_key = _digest(
        [b"speech-v1", python_version.encode(), _file_bytes(speech_requirements)]
    )
    webrtc_key = _digest(
        [b"webrtc-v1", python_version.encode(), _file_bytes(webrtc_requirements)]
    )

    def build_python(requirements: Path):
        def builder(destination: Path) -> None:
            _extract_python(archive, destination)
            _pip_install(destination / "Lib" / "site-packages", requirements)
        return builder

    bot = _atomic_cache(
        cache_root / "python" / f"bot-{bot_key}",
        build_python(bot_requirements),
    )
    voice = _atomic_cache(
        cache_root / "python" / f"voice-{voice_key}",
        build_python(voice_requirements),
    )

    def build_speech(destination: Path) -> None:
        target = destination / "Lib" / "site-packages"
        target.mkdir(parents=True, exist_ok=True)
        _pip_install(target, speech_requirements)

    speech = _atomic_cache(
        cache_root / "speech" / f"speech-{speech_key}",
        build_speech,
    )
    def build_webrtc(destination: Path) -> None:
        target = destination / "Lib" / "site-packages"
        target.mkdir(parents=True, exist_ok=True)
        _pip_install(target, webrtc_requirements, no_deps=True)

    webrtc = _atomic_cache(
        cache_root / "webrtc" / f"webrtc-{webrtc_key}",
        build_webrtc,
    )
    return {
        "bot_python": str(bot),
        "voice_python": str(voice),
        "speech": str(speech),
        "webrtc": str(webrtc),
        "bot_key": bot_key,
        "voice_key": voice_key,
        "speech_key": speech_key,
        "webrtc_key": webrtc_key,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare immutable DjGoo runtime layers in the self-hosted cache."
    )
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--python-embed-md5", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    payload = prepare(
        args.cache_root,
        args.python_version,
        args.python_embed_md5,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
