from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path


VERSION_LINE = re.compile(r"^Version:\s+(?P<version>\S+)\s*$", re.MULTILINE)
PIN_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-rc\.\d+)?(?:\+red\.\d+)?$")
DOWNLOAD_TEMPLATE = (
    "https://github.com/Cog-Creators/Lavalink-Jars/releases/download/"
    "{version}/Lavalink.jar"
)


class LavalinkContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def java_executable(runtime_java: Path) -> Path:
    candidates = (
        runtime_java / "bin" / "java.exe",
        runtime_java / "bin" / "java",
        runtime_java,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise LavalinkContractError(f"Could not locate Java below {runtime_java}")


def red_lavalink_pin(runtime_python: Path) -> str:
    command = [
        str(runtime_python),
        "-c",
        (
            "from redbot.cogs.audio.managed_node.version_pins import JAR_VERSION; "
            "print(str(JAR_VERSION))"
        ),
    ]
    try:
        output = subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LavalinkContractError(
            f"Could not read Red's Lavalink version pin: {exc}"
        ) from exc
    if not PIN_PATTERN.fullmatch(output):
        raise LavalinkContractError(f"Red returned an invalid Lavalink pin: {output!r}")
    return output


def reported_lavalink_version(java: Path, jar: Path) -> str:
    if not jar.is_file():
        raise LavalinkContractError(f"Lavalink jar is missing: {jar}")
    try:
        output = subprocess.check_output(
            [str(java), "-jar", str(jar), "--version"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LavalinkContractError(
            f"Could not inspect Lavalink jar {jar}: {exc}"
        ) from exc
    match = VERSION_LINE.search(output)
    if match is None:
        raise LavalinkContractError(
            f"Lavalink jar did not report a Version line: {output[:1000]}"
        )
    return match.group("version")


def download_exact_lavalink(version: str, destination: Path) -> str:
    url = DOWNLOAD_TEMPLATE.format(version=version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DjGoo portable builder"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise LavalinkContractError(
            f"Could not download Red-pinned Lavalink {version}: {exc}"
        ) from exc
    if temporary.stat().st_size < 1_000_000:
        size = temporary.stat().st_size
        temporary.unlink(missing_ok=True)
        raise LavalinkContractError(
            f"Downloaded Lavalink jar is unexpectedly small: {size} bytes"
        )
    temporary.replace(destination)
    return url


def ensure_red_lavalink_contract(
    *,
    runtime_python: Path,
    runtime_java: Path,
    candidate_jar: Path,
    output_jar: Path,
) -> dict[str, str | int]:
    """Select and verify the exact Lavalink jar pinned by packaged Red."""

    pin = red_lavalink_pin(runtime_python.resolve())
    java = java_executable(runtime_java.resolve())
    source = candidate_jar.resolve()
    source_version = ""
    if source.is_file():
        try:
            source_version = reported_lavalink_version(java, source)
        except LavalinkContractError:
            source_version = ""

    output_jar.parent.mkdir(parents=True, exist_ok=True)
    if source_version == pin:
        shutil.copy2(source, output_jar)
        source_url = "provided-candidate"
    else:
        source_url = download_exact_lavalink(pin, output_jar)

    actual = reported_lavalink_version(java, output_jar)
    if actual != pin:
        output_jar.unlink(missing_ok=True)
        raise LavalinkContractError(
            f"Lavalink version mismatch after selection: Red requires {pin}, jar reports {actual}"
        )

    return {
        "red_lavalink_version": pin,
        "lavalink_version": actual,
        "lavalink_sha256": sha256_file(output_jar),
        "lavalink_size": output_jar.stat().st_size,
        "source": source_url,
    }
