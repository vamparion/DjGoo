from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from voice.command_parser import FollowupResult, ParsedCommand


def command_to_queue_item(
    command: ParsedCommand,
    *,
    transcript: str | None = None,
    source: str = "voice",
    created_at: float | None = None,
) -> Dict[str, Any]:
    return {
        "type": "command",
        "source": source,
        "created_at": created_at if created_at is not None else time.time(),
        "intent": command.intent,
        "query": command.query,
        "playlist": command.playlist,
        "value": command.value,
        "confidence": command.confidence,
        "raw": transcript or command.raw,
    }


def followup_to_queue_item(
    followup: FollowupResult,
    *,
    transcript: str | None = None,
    source: str = "voice",
    created_at: float | None = None,
) -> Dict[str, Any]:
    return {
        "type": "followup",
        "source": source,
        "created_at": created_at if created_at is not None else time.time(),
        "action": followup.action,
        "index": followup.index,
        "raw": transcript or followup.raw,
    }


def append_queue_item(path: Path, item: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(item, ensure_ascii=True, separators=(",", ":")))
        fp.write("\n")


def drain_queue(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    processing_path = path.with_suffix(f"{path.suffix}.processing.{os.getpid()}")
    try:
        path.replace(processing_path)
    except OSError:
        return []

    items: List[Dict[str, Any]] = []
    try:
        with processing_path.open(encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    finally:
        processing_path.unlink(missing_ok=True)
    return items
