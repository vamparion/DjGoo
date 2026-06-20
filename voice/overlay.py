from __future__ import annotations

from typing import Dict

import requests

from .command_parser import FollowupResult, ParsedCommand


def send_overlay(webhook_url: str, title: str, description: str, *, color: int = 0x2F80ED) -> None:
    if not webhook_url:
        return
    payload = {
        "username": "DjGoo",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
            }
        ],
    }
    response = requests.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()


def describe_command(command: ParsedCommand) -> Dict[str, str]:
    if command.intent == "ignore":
        return {"title": "Ignored", "description": "No DjGoo wake phrase heard."}
    if command.intent == "play":
        return {"title": "DjGoo heard play", "description": f"Search request: `{command.query}`"}
    if command.intent in {"save_current_to_playlist", "save_last_to_playlist"}:
        target = "last song" if command.intent == "save_last_to_playlist" else "current song"
        return {
            "title": "DjGoo heard playlist save",
            "description": f"Save {target} to `{command.playlist}`.",
        }
    if command.intent in {"play_playlist", "shuffle_playlist"}:
        action = "Shuffle" if command.intent == "shuffle_playlist" else "Play"
        return {"title": "DjGoo heard playlist", "description": f"{action} `{command.playlist}`."}
    if command.intent == "volume":
        return {"title": "DjGoo heard volume", "description": f"Set volume to `{command.value}`."}
    if command.intent == "unknown":
        return {
            "title": "DjGoo heard you",
            "description": f"I heard `{command.query}`, but I do not know that command yet.",
        }
    return {"title": "DjGoo heard command", "description": f"Intent: `{command.intent}`"}


def describe_followup(result: FollowupResult) -> Dict[str, str]:
    if result.action == "choose":
        return {"title": "DjGoo heard choice", "description": f"Choice: `Number {result.index + 1}`"}
    if result.action == "neither":
        return {"title": "DjGoo heard neither", "description": "Cancelling those choices."}
    if result.action == "cancel":
        return {"title": "DjGoo cancelled", "description": "Okay, never mind."}
    if result.action == "expired":
        return {"title": "DjGoo choice expired", "description": "No choice heard within 15 seconds."}
    return {"title": "DjGoo is listening", "description": "Say `Number 1`, `Number 2`, or `Neither`."}
