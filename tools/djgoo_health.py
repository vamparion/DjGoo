from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


GOOD_PATTERNS = (
    re.compile(r"Connected to Discord\. Getting ready"),
    re.compile(r"discord\.gateway: Shard ID \d+ has connected"),
    re.compile(r"discord\.gateway: Shard ID \d+ has successfully RESUMED"),
    re.compile(r"Lavalink WS connected"),
)

BAD_PATTERNS = (
    re.compile(r"discord\.shard: Attempting a reconnect"),
    re.compile(r"ClientConnectorError: Cannot connect to host gateway"),
    re.compile(r"socket\.gaierror"),
    re.compile(r"Connect call failed"),
    re.compile(r"Lavalink Managed node startup failed"),
)


def recent_relevant_lines(path: Path, *, max_lines: int = 500) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def classify(lines: list[str]) -> tuple[bool, str]:
    last_good = -1
    last_bad = -1
    last_good_line = ""
    last_bad_line = ""
    for index, line in enumerate(lines):
        if any(pattern.search(line) for pattern in GOOD_PATTERNS):
            last_good = index
            last_good_line = line
        if any(pattern.search(line) for pattern in BAD_PATTERNS):
            last_bad = index
            last_bad_line = line
    if last_good < 0:
        return False, "No recent Discord/Lavalink ready line found."
    if last_bad > last_good:
        return False, f"Latest relevant line is unhealthy: {last_bad_line}"
    return True, f"Latest relevant line is healthy: {last_good_line}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DjGoo Redbot log health.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="DiscordBot project root.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    log_path = project_root / "data" / "discordbot" / "core" / "logs" / "red.log"
    healthy, reason = classify(recent_relevant_lines(log_path))
    print(reason, flush=True)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
