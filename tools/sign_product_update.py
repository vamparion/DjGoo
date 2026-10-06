from __future__ import annotations

import argparse
import base64
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from tools.build_windows_product import directory_identity


def build_feed(args: argparse.Namespace) -> Path:
    layer_root = args.layer.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / args.artifact
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in layer_root.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(layer_root).as_posix())

    expected_hash, expected_size = directory_identity(layer_root)
    with tempfile.TemporaryDirectory(prefix="djgoo-update-verify-") as temporary:
        with zipfile.ZipFile(artifact) as archive:
            archive.extractall(temporary)
        if directory_identity(Path(temporary)) != (expected_hash, expected_size):
            raise RuntimeError("Update ZIP bytes do not match the source layer identity")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    target = manifest[args.layer_name]
    target.update({
        "generation": args.generation,
        "version": args.version,
        "sha256": expected_hash,
        "size": expected_size,
        "location": args.location,
        "artifact": args.artifact,
    })
    manifest_bytes = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    private_key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    signature = private_key.sign(manifest_bytes, padding.PKCS1v15(), hashes.SHA256())
    feed = (
        b'{"schema":1,"manifest":' + manifest_bytes
        + b',"signature":' + json.dumps(base64.b64encode(signature).decode("ascii")).encode("ascii")
        + b',"artifacts":' + json.dumps({args.artifact: str(artifact)}, separators=(",", ":")).encode("utf-8")
        + b"}"
    )
    destination = output / "feed.json"
    destination.write_bytes(feed)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and sign a verified DjGoo layer update feed.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--layer", type=Path, required=True)
    parser.add_argument("--layer-name", choices=("application", "python_red", "java", "lavalink", "webrtc", "speech"), required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    print(build_feed(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
