from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


PLACEHOLDER_WEBHOOK = "PASTE_NEW_WEBHOOK_URL_HERE"


def load_project_secrets(project_root: Path) -> Dict[str, Any]:
    path = project_root / "config" / "secrets.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as fp:
        data = json.load(fp)
    webhook_url = str(data.get("webhook_url", "")).strip()
    if webhook_url == PLACEHOLDER_WEBHOOK:
        webhook_url = ""
    data["webhook_url"] = webhook_url
    voice = data.setdefault("voice", {})
    voice.setdefault("model", "base.en")
    voice.setdefault("chunk_seconds", 4)
    voice.setdefault("language", "en")
    voice.setdefault("compute_type", "int8")
    voice.setdefault("queue_path", str(project_root / "data" / "voice-command-queue.jsonl"))
    return data
