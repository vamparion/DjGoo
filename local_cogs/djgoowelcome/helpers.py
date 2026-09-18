from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


PLACEHOLDER_WEBHOOK = "PASTE_NEW_WEBHOOK_URL_HERE"
CHAT_WAKE_RE = re.compile(
    r"^\s*(?:(?:hey|yo|okay|ok)\s+)?(?:dj\s*goo|djgoo|dee\s*jay|d\s*j|dj)\b[:,]?\s*",
    re.IGNORECASE,
)
PLAYBACK_CONTROL_BUTTONS = [
    {"label": "Pause/Resume", "style": "secondary", "intent": "toggle_pause", "row": 0},
    {"label": "Skip", "style": "primary", "intent": "skip", "row": 0},
    {"label": "Replay", "style": "secondary", "intent": "replay", "row": 0},
    {"label": "Stop", "style": "danger", "intent": "stop", "row": 0},
    {"label": "Queue", "style": "secondary", "intent": "queue", "row": 0},
    {"label": "Vol -", "style": "secondary", "intent": "volume_down", "row": 1},
    {"label": "Vol +", "style": "secondary", "intent": "volume_up", "row": 1},
    {"label": "Like", "style": "success", "intent": "station_like_current", "row": 1},
    {"label": "More Like", "style": "secondary", "intent": "station_more_like_current", "row": 1},
    {"label": "Less Like", "style": "secondary", "intent": "station_less_like_current", "row": 1},
    {"label": "Ban", "style": "danger", "intent": "station_ban_current", "row": 2},
]


def should_send_welcome(member: Any, before: Any, after: Any) -> bool:
    if getattr(member, "bot", False):
        return False
    before_channel = getattr(before, "channel", None)
    after_channel = getattr(after, "channel", None)
    return before_channel is None and after_channel is not None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def parse_djgoo_chat_command(content: str) -> Optional[str]:
    match = CHAT_WAKE_RE.search(content)
    if not match:
        return None
    command = _normalize(content[match.end() :])
    return command or None


def load_secrets(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"webhook_url": "", "voice": {}, "voice_gateway": {}}

    with path.open(encoding="utf-8-sig") as fp:
        data = json.load(fp)

    webhook_url = str(data.get("webhook_url", "")).strip()
    if webhook_url == PLACEHOLDER_WEBHOOK:
        webhook_url = ""
    voice = data.get("voice", {})
    if not isinstance(voice, dict):
        voice = {}
    voice_gateway = data.get("voice_gateway", {})
    if not isinstance(voice_gateway, dict):
        voice_gateway = {}
    return {
        "webhook_url": webhook_url,
        "voice": voice,
        "voice_gateway": voice_gateway,
    }


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

    description_parts.append("Discord control bridge received it.")
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


def build_fast_control_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    intent = str(item.get("intent", "unknown")).strip().lower()
    labels = {
        "skip": "Skipping",
        "stop": "Stopping",
        "pause": "Pausing",
        "resume": "Resuming",
        "toggle_pause": "Pause/resume",
        "volume_up": "Volume up",
        "volume_down": "Volume down",
    }
    label = labels.get(intent, intent.replace("_", " ").title() or "Command")
    raw = str(item.get("raw", "")).strip()
    description = f"Heard: `{raw}`" if raw else "Voice control received."
    return {
        "username": "DjGoo",
        "content": f"DjGoo: {label}.",
        "embeds": [
            {
                "title": label,
                "description": description,
                "color": 0x2F80ED,
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


def build_playback_control_embed(
    track: Dict[str, Any],
    *,
    station_name: Optional[str] = None,
) -> Dict[str, Any]:
    title = str(track.get("title", "")).strip() or "Now playing"
    uri = str(track.get("uri", "")).strip()
    description_lines = []
    if station_name:
        description_lines.append(f"Station: **{station_name}**")
    if uri:
        description_lines.append(f"[Open track]({uri})")
    description_lines.append("Use the buttons below to control DjGoo.")
    return {
        "title": title[:256],
        "description": "\n".join(description_lines)[:4096],
        "color": 0x2F80ED,
        "footer": {"text": "Playback buttons are available for everyone in chat."},
    }
