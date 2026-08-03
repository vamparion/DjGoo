from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


DEFAULT_MODULES = {
    "java.base",
    "java.compiler",
    "java.datatransfer",
    "java.desktop",
    "java.logging",
    "java.management",
    "java.naming",
    "java.net.http",
    "java.prefs",
    "java.rmi",
    "java.security.jgss",
    "java.sql",
    "java.transaction.xa",
    "java.xml",
    "jdk.crypto.ec",
    "jdk.unsupported",
}


class MinimalJreError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _java_version(java_home: Path) -> str:
    java = java_home / "bin" / "java.exe"
    if not java.is_file():
        java = java_home / "bin" / "java"
    if not java.is_file():
        raise MinimalJreError(f"Java executable is missing under {java_home}")
    result = subprocess.run(
        [str(java), "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0 or not output:
        raise MinimalJreError(f"Could not query Java version: {output}")
    return output.splitlines()[0].strip()


def _jdeps_modules(java_home: Path, jar: Path) -> set[str]:
    jdeps = java_home / "bin" / "jdeps.exe"
    if not jdeps.is_file():
        jdeps = java_home / "bin" / "jdeps"
    if not jdeps.is_file():
        return set(DEFAULT_MODULES)
    result = subprocess.run(
        [
            str(jdeps),
            "--ignore-missing-deps",
            "--multi-release",
            "17",
            "--print-module-deps",
            str(jar),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set(DEFAULT_MODULES)
    text = (result.stdout or "").strip().splitlines()
    modules = {
        value.strip()
        for value in (text[-1].split(",") if text else ())
        if re.fullmatch(r"[A-Za-z0-9_.]+", value.strip())
    }
    # jdeps cannot see every module loaded reflectively by Lavalink/plugins.
    # Retain a conservative runtime-only baseline while still excluding the
    # compiler toolchain, source archives, headers, man pages, and full JDK.
    modules.update(DEFAULT_MODULES)
    return modules


def _cache_key(java_version: str, jar: Path, modules: set[str]) -> str:
    digest = hashlib.sha256()
    digest.update(java_version.encode("utf-8"))
    digest.update(b"\0")
    digest.update(sha256_file(jar).encode("ascii"))
    digest.update(b"\0")
    digest.update(",".join(sorted(modules)).encode("ascii"))
    digest.update(b"\0jlink-v1")
    return digest.hexdigest()[:20]


def _validate(runtime: Path, jar: Path) -> None:
    java = runtime / "bin" / "java.exe"
    if not java.is_file():
        java = runtime / "bin" / "java"
    result = subprocess.run(
        [str(java), "-jar", str(jar), "--version"],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0 or "Version:" not in output:
        raise MinimalJreError(
            "Minimal Java runtime could not execute the pinned Audio Engine: "
            + output[-1200:]
        )


def build(java_home: Path, jar: Path, cache_root: Path) -> dict[str, object]:
    java_home = java_home.resolve()
    jar = jar.resolve()
    cache_root = cache_root.resolve()
    if not jar.is_file():
        raise MinimalJreError(f"Pinned Lavalink jar is missing: {jar}")
    version = _java_version(java_home)
    modules = _jdeps_modules(java_home, jar)
    key = _cache_key(version, jar, modules)
    destination = cache_root / f"jre-{key}"
    marker = destination / "djgoo-jre.json"
    if marker.is_file():
        _validate(destination, jar)
        return {
            "path": str(destination),
            "cache_key": key,
            "java_version": version,
            "modules": sorted(modules),
            "cached": True,
        }

    jlink = java_home / "bin" / "jlink.exe"
    if not jlink.is_file():
        jlink = java_home / "bin" / "jlink"
    if not jlink.is_file():
        raise MinimalJreError(f"jlink is missing under {java_home}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f"jre-{key}-", dir=destination.parent))
    shutil.rmtree(temporary)
    try:
        result = subprocess.run(
            [
                str(jlink),
                "--add-modules",
                ",".join(sorted(modules)),
                "--strip-debug",
                "--no-header-files",
                "--no-man-pages",
                "--compress=2",
                "--output",
                str(temporary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = ((result.stdout or "") + (result.stderr or "")).strip()
            raise MinimalJreError(f"jlink failed: {detail}")
        _validate(temporary, jar)
        (temporary / "djgoo-jre.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "cache_key": key,
                    "java_version": version,
                    "lavalink_sha256": sha256_file(jar),
                    "modules": sorted(modules),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "path": str(destination),
        "cache_key": key,
        "java_version": version,
        "modules": sorted(modules),
        "cached": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a cached minimal Java runtime for DjGoo's Audio Engine."
    )
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--lavalink-jar", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.java_home, args.lavalink_jar, args.cache_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
