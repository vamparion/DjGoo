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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_bundle(bundle: Path, manifest: dict[str, object]) -> None:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise SpeechRuntimeBuildError("Speech runtime manifest contains no files")
    listed = {
        str(item.get("path") or ""): item
        for item in raw_files
        if isinstance(item, dict)
    }
    if len(listed) != len(raw_files) or "" in listed:
        raise SpeechRuntimeBuildError("Speech runtime manifest contains invalid file entries")
    with zipfile.ZipFile(bundle, "r") as archive:
        if archive.testzip() is not None:
            raise SpeechRuntimeBuildError("Speech runtime ZIP failed its integrity check")
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        if len(names) != len(set(names)) or set(names) != set(listed):
            raise SpeechRuntimeBuildError(
                "Speech runtime ZIP membership does not match its manifest"
            )
        for name in names:
            data = archive.read(name)
            metadata = listed[name]
            raw_size = metadata.get("size")
            expected_size = int(raw_size) if raw_size is not None else -1
            if len(data) != expected_size:
                raise SpeechRuntimeBuildError(f"Speech runtime size mismatch for {name}")
            if _sha256(data) != str(metadata.get("sha256") or "").lower():
                raise SpeechRuntimeBuildError(f"Speech runtime hash mismatch for {name}")


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
            data = path.read_bytes()
            archive.writestr(relative.as_posix(), data)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "size": len(data),
                    "sha256": _sha256(data),
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
    verify_bundle(output_zip, manifest)
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
