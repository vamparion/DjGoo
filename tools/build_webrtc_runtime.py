from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> Path:
    output = output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    site_packages = output / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    requirements = PROJECT_ROOT / "requirements-webrtc.txt"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-deps",
            "--target",
            str(site_packages),
            "--requirement",
            str(requirements),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    files = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": digest})
    (output / "layer-manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "kind": "djgoo-host-webrtc-runtime",
                "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic Host WebRTC dependency layer.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
