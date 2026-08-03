from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "launcher" / "windows" / "DjGooThinLauncher.cs"
LAUNCHERS = ("DjGoo.exe", "DjGoo Mini Player.exe", "DjGoo Voice.exe")


class ThinLauncherBuildError(RuntimeError):
    pass


def find_csc() -> Path:
    configured = str(os.environ.get("CSC_EXE") or "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET"
        / "Framework64"
        / "v4.0.30319"
        / "csc.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET"
        / "Framework"
        / "v4.0.30319"
        / "csc.exe",
    ]
    located = shutil.which("csc.exe") or shutil.which("csc")
    if located:
        candidates.insert(0, Path(located))
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise ThinLauncherBuildError(
        "The Windows C# compiler was not found. Windows 10/11 normally provides "
        "the .NET Framework compiler under Microsoft.NET/Framework64."
    )


def build(output: Path) -> list[Path]:
    if os.name != "nt":
        raise ThinLauncherBuildError("DjGoo Windows launchers must be built on Windows")
    if not SOURCE.is_file():
        raise ThinLauncherBuildError(f"Thin launcher source is missing: {SOURCE}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = find_csc()
    built: list[Path] = []
    for filename in LAUNCHERS:
        destination = output / filename
        destination.unlink(missing_ok=True)
        command = [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:x64",
            "/optimize+",
            "/deterministic+",
            "/reference:System.dll",
            "/reference:System.Windows.Forms.dll",
            f"/out:{destination}",
            str(SOURCE),
        ]
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not destination.is_file():
            detail = (result.stdout or "") + (result.stderr or "")
            raise ThinLauncherBuildError(
                f"Could not build {filename} with {compiler}: {detail.strip()}"
            )
        if destination.stat().st_size > 512 * 1024:
            raise ThinLauncherBuildError(
                f"Thin launcher is unexpectedly large: {destination.stat().st_size} bytes"
            )
        built.append(destination)
    return built


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile small Windows launchers that start DjGoo's shared runtime."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in build(args.output):
        print(f"built {path.name}: {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
