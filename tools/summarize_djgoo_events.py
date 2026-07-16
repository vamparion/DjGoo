from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_events(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    events = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize recent DjGoo operational events.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="DiscordBot project root.",
    )
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    events = read_events(project_root / "logs" / "djgoo-events.jsonl", args.limit)
    if not events:
        print("No DjGoo operational events found yet.")
        return 1

    counts = Counter(str(item.get("event", "unknown")) for item in events)
    print(f"Events read: {len(events)}")
    print("\nTop event types:")
    for event, count in counts.most_common(20):
        print(f"  {count:4} {event}")

    print("\nRecent important events:")
    important_prefixes = (
        "voice.",
        "bridge.command",
        "play.",
        "radio.",
        "nuclear.",
        "discord.controls",
        "chat.command",
    )
    for item in events[-80:]:
        event = str(item.get("event", ""))
        if not event.startswith(important_prefixes):
            continue
        ts = item.get("ts", "")
        summary = {key: value for key, value in item.items() if key not in {"ts", "event"}}
        print(f"  {ts} {event} {json.dumps(summary, ensure_ascii=True)[:500]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
