from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


PLACEHOLDER_WEBHOOK = "PASTE_NEW_WEBHOOK_URL_HERE"


def should_send_welcome(member: Any, before: Any, after: Any) -> bool:
    if getattr(member, "bot", False):
        return False
    before_channel = getattr(before, "channel", None)
    after_channel = getattr(after, "channel", None)
    return before_channel is None and after_channel is not None


def load_secrets(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"webhook_url": "", "voice": {}}

    with path.open(encoding="utf-8-sig") as fp:
        data = json.load(fp)

    webhook_url = str(data.get("webhook_url", "")).strip()
    if webhook_url == PLACEHOLDER_WEBHOOK:
        webhook_url = ""
    voice = data.get("voice", {})
    if not isinstance(voice, dict):
        voice = {}
    return {"webhook_url": webhook_url, "voice": voice}


def build_welcome_payload(display_name: str, voice_channel_name: str) -> Dict[str, Any]:
    description = "\n".join(
        [
            f"{display_name} joined voice. DjGoo can be controlled from chat.",
            "",
            "**Type these in chat:**",
            "`DjGoo play <song or URL>`",
            "`DjGoo, skip`",
            "`DjGoo pause` / `DjGoo resume`",
            "`DjGoo stop`",
            "`DjGoo queue`",
            "`DjGoo now`",
            "`DjGoo volume 50`",
            "`DjGoo disconnect`",
            "",
            "The classic `!` prefix still works too, like `!play <song>`.",
        ]
    )

    return {
        "username": "DjGoo",
        "embeds": [
            {
                "title": f"Welcome to {voice_channel_name}",
                "description": description,
                "color": 0x2F80ED,
            }
        ],
    }


def build_voice_command_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    if item.get("type") == "followup":
        action = str(item.get("action", "unknown")).replace("_", " ").title()
        raw = str(item.get("raw", "")).strip()
        index = item.get("index")
        details = f"Choice {int(index) + 1}" if isinstance(index, int) else action
        title = f"Voice Choice: {details}"
        description_parts = [f"Handled follow-up: **{action}**"]
        if raw:
            description_parts.append(f"Heard: `{raw}`")
    else:
        intent = str(item.get("intent", "unknown")).replace("_", " ").title()
        raw = str(item.get("raw", "")).strip()
        query = str(item.get("query", "")).strip()
        playlist = str(item.get("playlist", "")).strip()
        value = item.get("value")
        title = f"Voice Command: {intent}"
        description_parts = [f"Queued action: **{intent}**"]
        if query:
            description_parts.append(f"Song/search: `{query}`")
        if playlist:
            description_parts.append(f"Playlist: `{playlist}`")
        if value is not None:
            description_parts.append(f"Value: `{value}`")
        if raw:
            description_parts.append(f"Heard: `{raw}`")

    description_parts.append("Discord control bridge received it. Music action wiring is next.")
    return {
        "username": "DjGoo",
        "embeds": [
            {
                "title": title,
                "description": "\n".join(description_parts),
                "color": 0x27AE60,
            }
        ],
    }


def build_station_track_payload(
    *,
    station_name: str,
    track: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    title = str(track.get("title", "")).strip() or "Radio pick"
    uri = str(track.get("uri", "")).strip()
    description_lines = [
        f"Station: **{station_name}**",
        f"Why: {reason}",
    ]
    if uri:
        description_lines.append(f"[Open track]({uri})")
    return {
        "username": "DjGoo",
        "embeds": [
            {
                "title": title[:256],
                "description": "\n".join(description_lines)[:4096],
                "color": 0x9B51E0,
                "footer": {
                    "text": "DjGoo like this | more like this | less like this | don't play this again"
                },
            }
        ],
    }
