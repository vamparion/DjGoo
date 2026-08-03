from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path


ZIP_NAME = "DjGoo-SpeechRuntime-win-x64.zip"
MANIFEST_NAME = "DjGoo-SpeechRuntime.json"


class SpeechRuntimeBuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(layer: Path, output_zip: Path, output_manifest: Path, version: str) -> dict[str, object]:
    layer = layer.resolve()
    site_packages = layer / "Lib" / "site-packages"
    if not site_packages.is_dir() or not (site_packages / "faster_whisper").is_dir():
        raise SpeechRuntimeBuildError(
            "Speech layer must contain Lib/site-packages/faster_whisper"
        )
    files = sorted(path for path in layer.rglob("*") if path.is_file())
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    output_zip.unlink(missing_ok=True)
    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(
        output_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in files:
            relative = Path("runtime") / "speech" / path.relative_to(layer)
            archive.write(path, relative.as_posix())
            entries.append(
                {
                    "path": relative.as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    normalized = version.strip().lstrip("v")
    manifest: dict[str, object] = {
        "schema": 1,
        "product": "DjGoo Speech Runtime",
        "version": normalized,
        "release_tag": f"v{normalized}",
        "bundle_asset": ZIP_NAME,
        "bundle_size": output_zip.stat().st_size,
        "bundle_sha256": sha256_file(output_zip),
        "runtime_generation": 4,
        "files": entries,
    }
    temporary = output_manifest.with_suffix(output_manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output_manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DjGoo's optional speech runtime asset.")
    parser.add_argument("--layer", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(args.layer, args.output_zip, args.output_manifest, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
