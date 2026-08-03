from __future__ import annotations

from pathlib import Path


TARGETS = (
    Path(".github/workflows/fast-app-release.yml"),
    Path(".github/workflows/portable-release.yml"),
    Path(".github/workflows/repair-release-assets.yml"),
)
OLD = "shell: powershell"
NEW = 'shell: powershell -NoProfile -ExecutionPolicy Bypass -Command ". \'{0}\'"'


def main() -> int:
    total = 0
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        count = text.count(OLD)
        if count:
            path.write_text(text.replace(OLD, NEW), encoding="utf-8")
        total += count
        print(f"updated {path}: {count} shell declarations")

    remaining = [str(path) for path in TARGETS if OLD in path.read_text(encoding="utf-8")]
    if remaining:
        raise RuntimeError("Unrepaired PowerShell declarations remain: " + ", ".join(remaining))
    if total:
        print(f"updated {total} release workflow shell declarations")
    else:
        print("release workflow shells are already repaired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
