from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from tools.app_layout import current_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GENERATION = 4


class LayeredUpdateRootError(RuntimeError):
    pass


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise LayeredUpdateRootError(f"Required update file is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build(
    *,
    output: Path,
    product: str,
    version: str,
    app_layer: Path,
    launchers: Path,
) -> Path:
    normalized_product = product.strip().lower()
    if normalized_product not in {"host", "voice"}:
        raise LayeredUpdateRootError(f"Unsupported product: {product}")
    normalized_version = version.strip().lstrip("v")
    output = output.resolve()
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    destination = output / "app" / normalized_version
    if not app_layer.is_dir():
        raise LayeredUpdateRootError(f"Application layer is missing: {app_layer}")
    shutil.copytree(app_layer, destination, dirs_exist_ok=True)
    (output / "current.json").write_text(
        json.dumps(current_payload(normalized_version), indent=2) + "\n",
        encoding="utf-8",
    )

    if normalized_product == "host":
        for name in ("DjGoo.exe", "DjGoo Mini Player.exe"):
            _copy(launchers / name, output / name)
        # Alpha.24's updater resumes through this root-level adapter before the
        # new thin launcher takes over. Future launches use the app layer.
        _copy(
            PROJECT_ROOT / "tools" / "layered_stack_bootstrap.py",
            output / "tools" / "djgoo_stack.py",
        )
        for name in (
            "apply_update.py",
            "complete_launcher_update.py",
            "portable_environment.py",
            "app_layout.py",
        ):
            _copy(PROJECT_ROOT / "tools" / name, output / "tools" / name)
    else:
        _copy(launchers / "DjGoo Voice.exe", output / "DjGoo Voice.exe")
        for name in (
            "apply_voice_update.py",
            "voice_update_client.py",
            "update_client.py",
            "update_auth.py",
            "portable_environment.py",
            "app_layout.py",
        ):
            _copy(PROJECT_ROOT / "tools" / name, output / "tools" / name)

    data = output / "data" / "installed-version.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": normalized_version,
                "release_tag": f"v{normalized_version}",
                "runtime_generation": RUNTIME_GENERATION,
                "package_layout": "versioned-app-v1",
                "product": normalized_product,
                "installed_at": time.time(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a small application-only DjGoo update root."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product", choices=("host", "voice"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app-layer", type=Path, required=True)
    parser.add_argument("--launchers", type=Path, required=True)
    args = parser.parse_args()
    build(
        output=args.output,
        product=args.product,
        version=args.version,
        app_layer=args.app_layer,
        launchers=args.launchers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
