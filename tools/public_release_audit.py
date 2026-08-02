from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Iterable


REQUIRED_PUBLIC_FILES = {
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "config/secrets.example.json",
}

FORBIDDEN_TRACKED_PATHS = {
    "config/secrets.json",
    "config/update-auth.json",
    "data/voice-remote-credential.json",
    "data/relay-identity/relay-signing-ed25519.key",
    "data/relay-identity/relay-encryption-x25519.key",
}

FORBIDDEN_TRACKED_PREFIXES = (
    ".localappdata/",
    ".venv/",
    ".voice-venv/",
    "data/update-backups/",
    "logs/",
)

FORBIDDEN_SUFFIXES = (
    ".p12",
    ".pfx",
    ".key",
)

TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".cmd",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

SCAN_EXCLUSIONS = {
    "tools/public_release_audit.py",
    "tests/test_public_release_audit.py",
}

SECRET_PATTERNS = (
    (
        "GitHub legacy token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
    ),
    (
        "GitHub fine-grained token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b"),
    ),
    (
        "Discord webhook URL",
        re.compile(
            r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/"
            r"\d{10,}/[A-Za-z0-9._-]{20,}"
        ),
    ),
    (
        "Discord MFA token",
        re.compile(r"\bmfa\.[A-Za-z0-9_-]{60,}\b"),
    ),
    (
        "AWS access key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "private key",
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)

ASSIGNED_SECRET = re.compile(
    r"(?i)[\"'](?:bot_token|client_secret|device_token|webhook_url|private_key)"
    r"[\"']\s*[:=]\s*[\"']([^\"']{20,})[\"']"
)

PLACEHOLDER_WORDS = {
    "example",
    "paste",
    "placeholder",
    "replace",
    "sample",
    "your_",
    "your-",
}


class PublicReleaseAuditError(RuntimeError):
    pass


def _git_tracked_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [
        value.decode("utf-8", errors="strict").replace("\\", "/")
        for value in result.stdout.split(b"\0")
        if value
    ]


def tracked_files(root: Path) -> list[str]:
    tracked = _git_tracked_files(root)
    if tracked is not None:
        return sorted(dict.fromkeys(tracked))
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or any(word in lowered for word in PLACEHOLDER_WORDS)
        or lowered.startswith(("wss://your", "https://your"))
    )


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def audit_public_release(
    root: Path,
    *,
    paths: Iterable[str] | None = None,
) -> list[str]:
    root = root.resolve()
    tracked = sorted(dict.fromkeys(paths or tracked_files(root)))
    tracked_set = set(tracked)
    failures: list[str] = []

    missing = sorted(REQUIRED_PUBLIC_FILES.difference(tracked_set))
    if missing:
        failures.append("missing public project files: " + ", ".join(missing))

    for relative in tracked:
        normalized = relative.replace("\\", "/").lstrip("./")
        lowered = normalized.lower()
        if normalized in FORBIDDEN_TRACKED_PATHS:
            failures.append(f"private runtime file is tracked: {normalized}")
        if any(lowered.startswith(prefix.lower()) for prefix in FORBIDDEN_TRACKED_PREFIXES):
            failures.append(f"private runtime path is tracked: {normalized}")
        if lowered.endswith(FORBIDDEN_SUFFIXES):
            failures.append(f"private key/container file is tracked: {normalized}")
        if normalized in SCAN_EXCLUSIONS:
            continue
        path = root / normalized
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _read_text(path)
        if text is None:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible {label} in tracked file: {normalized}")
        for match in ASSIGNED_SECRET.finditer(text):
            value = match.group(1)
            if not _looks_like_placeholder(value):
                failures.append(
                    f"possible assigned secret in tracked file: {normalized}"
                )
                break

    gitignore = _read_text(root / ".gitignore") or ""
    ignored = {
        line.strip().replace("\\", "/")
        for line in gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for required_ignore in (
        "config/secrets.json",
        "data/",
        "logs/",
        ".localappdata/",
    ):
        if required_ignore not in ignored:
            failures.append(f".gitignore does not exclude {required_ignore}")

    return sorted(dict.fromkeys(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject secrets and private runtime state before DjGoo becomes public."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    failures = audit_public_release(args.root)
    if failures:
        for failure in failures:
            print(f"PUBLIC RELEASE AUDIT FAILED: {failure}")
        return 1
    print("Public release audit passed: tracked files contain no detected secrets or private runtime state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
