from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.apply_update import (
    apply_staged_update,
    extract_verified_bundle,
    load_manifest,
    validate_bundle,
)


ALPHA25 = "0.3.0-alpha.25"
ALPHA26 = "0.3.0-alpha.26"
OLD_PTH_LINE = (
    "import os,sys; "
    "sys.path.insert(0,os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','speech','Lib','site-packages')) "
    "if os.path.isdir(os.path.join(os.environ.get('DJGOO_HOME',''),"
    "'runtime','speech','Lib','site-packages')) else None; "
    "sys.path.insert(0,os.environ['DJGOO_APP_ROOT']) "
    "if os.path.isdir(os.environ.get('DJGOO_APP_ROOT','')) else None"
)


class UpgradeSmokeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_smoke(
    *,
    runtime_layer: Path,
    bundle: Path,
    manifest_path: Path,
    output: Path,
) -> None:
    output = output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    python_root = output / "runtime" / "python-bot"
    shutil.copytree(runtime_layer.resolve(), python_root)
    python = python_root / "python.exe"
    pth = next(python_root.glob("python*._pth"), None)
    root_pth = python_root / "Lib" / "site-packages" / "djgoo-root.pth"
    if not python.is_file() or pth is None or not root_pth.is_file():
        raise UpgradeSmokeError("The alpha.25 Host runtime fixture is incomplete")
    root_pth.write_text("../../../..\n" + OLD_PTH_LINE + "\n", encoding="ascii")
    if "runtime','webrtc" in root_pth.read_text(encoding="ascii"):
        raise UpgradeSmokeError("The alpha.25 runtime fixture unexpectedly knows WebRTC")

    app25 = output / "app" / ALPHA25
    app25.mkdir(parents=True)
    (output / "current.json").write_text(
        json.dumps({"schema": 1, "version": ALPHA25, "path": f"app/{ALPHA25}"}),
        encoding="utf-8",
    )
    installed_version = output / "data" / "installed-version.json"
    installed_version.parent.mkdir(parents=True)
    installed_version.write_text(json.dumps({"version": ALPHA25}), encoding="utf-8")
    secrets = output / "config" / "secrets.json"
    secrets.parent.mkdir(parents=True)
    secrets.write_bytes(b'{"paired":"alpha25-secret"}')
    pairing = output / "data" / "djgoo-pairing.db"
    pairing.write_bytes(b"alpha25-pairing-database")

    python_hash = _sha256(python)
    pth_hash = _sha256(root_pth)
    manifest = load_manifest(manifest_path)
    if str(manifest.get("version")) != ALPHA26:
        raise UpgradeSmokeError("The migration bundle is not alpha.26")
    expected = validate_bundle(bundle, manifest)
    staging = output.parent / (output.name + "-staging")
    backup = output.parent / (output.name + "-backup")
    extract_verified_bundle(bundle, staging, expected)
    apply_staged_update(output, staging, manifest, backup)

    installed = json.loads(installed_version.read_text(encoding="utf-8"))
    if installed.get("version") != ALPHA26:
        raise UpgradeSmokeError("The updater did not install alpha.26")
    if secrets.read_bytes() != b'{"paired":"alpha25-secret"}':
        raise UpgradeSmokeError("The updater changed Host secrets")
    if pairing.read_bytes() != b"alpha25-pairing-database":
        raise UpgradeSmokeError("The updater changed the pairing database")
    if _sha256(python) != python_hash or _sha256(root_pth) != pth_hash:
        raise UpgradeSmokeError("The updater replaced or modified the alpha.25 Python runtime")

    app26 = output / "app" / ALPHA26
    environment = dict(os.environ)
    environment["DJGOO_HOME"] = str(output)
    environment["DJGOO_APP_ROOT"] = str(app26)
    command = (
        "from voice.webrtc_transport import WebRtcSignalManager; "
        "manager=WebRtcSignalManager(object()); "
        "assert manager.available() is True; "
        "import aiortc,av,pylibsrtp; "
        "print('ALPHA25_TO_ALPHA26_WEBRTC_OK', aiortc.__version__, av.__version__, pylibsrtp.__version__)"
    )
    completed = subprocess.run(
        [str(python), "-c", command],
        cwd=output,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise UpgradeSmokeError(
            "The preserved alpha.25 runtime could not load WebRTC after update:\n"
            + completed.stdout
            + completed.stderr
        )
    print(completed.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test alpha.25 to alpha.26 Host WebRTC migration.")
    parser.add_argument("--runtime-layer", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_smoke(
        runtime_layer=args.runtime_layer,
        bundle=args.bundle,
        manifest_path=args.manifest,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
