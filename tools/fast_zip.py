from __future__ import annotations

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path


class FastZipError(RuntimeError):
    pass


def create_zip(source: Path, destination: Path) -> str:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise FastZipError(f"ZIP source directory does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    seven_zip = shutil.which("7z.exe") or shutil.which("7z")
    if seven_zip:
        result = subprocess.run(
            [
                seven_zip,
                "a",
                "-tzip",
                "-mx=5",
                "-mmt=on",
                str(destination),
                source.name,
            ],
            cwd=source.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and destination.is_file():
            return "7zip-multithreaded"
        destination.unlink(missing_ok=True)

    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            archive.write(path, (Path(source.name) / path.relative_to(source)).as_posix())
    return "python-zipfile"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a standard DjGoo ZIP efficiently.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    method = create_zip(args.source, args.output)
    print(f"created {args.output} with {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
