from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPAIR_BRANCH = os.environ.get("REPAIR_BRANCH", "release/alpha25-shell-fix-generated")
REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TARGETS = (
    ".github/workflows/fast-app-release.yml",
    ".github/workflows/portable-release.yml",
    ".github/workflows/repair-release-assets.yml",
)


def run(*args: str, capture: bool = False) -> str:
    environment = dict(os.environ)
    environment.pop("GIT_DIR", None)
    environment.pop("GIT_WORK_TREE", None)
    completed = subprocess.run(
        list(args),
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=capture,
    )
    return (completed.stdout or "").strip()


def main() -> int:
    repaired = {
        path: (PROJECT_ROOT / path).read_text(encoding="utf-8")
        for path in TARGETS
    }

    run("git", "config", "--global", "user.name", "github-actions[bot]")
    run(
        "git",
        "config",
        "--global",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )
    run(
        "git",
        "config",
        "--global",
        "--add",
        "safe.directory",
        PROJECT_ROOT.as_posix(),
    )
    run("git", "fetch", "origin", "main")
    run("git", "switch", "--force-create", REPAIR_BRANCH, "origin/main")

    for path, content in repaired.items():
        destination = PROJECT_ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    run("git", "add", *TARGETS)
    run("git", "diff", "--cached", "--check")

    status = run("git", "diff", "--cached", "--name-only", capture=True)
    if not status:
        print("release workflow shells already repaired")
        return 0

    run("git", "commit", "-m", "Run release workflows with PowerShell bypass")
    run("git", "push", "--force", "origin", f"HEAD:{REPAIR_BRANCH}")

    raw = run(
        "gh",
        "pr",
        "list",
        "--repo",
        REPOSITORY,
        "--head",
        REPAIR_BRANCH,
        "--base",
        "main",
        "--state",
        "open",
        "--json",
        "number",
        capture=True,
    )
    existing = json.loads(raw or "[]")
    if existing:
        print(f"repair PR already open: #{existing[0]['number']}")
        return 0

    run(
        "gh",
        "pr",
        "create",
        "--repo",
        REPOSITORY,
        "--base",
        "main",
        "--head",
        REPAIR_BRANCH,
        "--title",
        "Run alpha.25 release workflows with PowerShell bypass",
        "--body",
        (
            "AEGIS blocks temporary PowerShell scripts under its machine execution policy. "
            "This applies the explicit -ExecutionPolicy Bypass shell already used by trusted "
            "CI to every fast release, full package, and final verifier PowerShell step."
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
