from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


WAKE_RE = re.compile(
    r"^\s*(?:(?:hey|yo|okay|ok)\s+)?(?:dj\s*goo|djgoo|dee\s*jay|d\s*j|dj)\b[:,]?\s*",
    re.IGNORECASE,
)
NUMBER_WORDS = [
    ("first", 1),
    ("second", 2),
    ("third", 3),
    ("fourth", 4),
    ("one", 1),
    ("two", 2),
    ("three", 3),
    ("four", 4),
]
CHOICE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class ParsedCommand:
    intent: str
    query: str = ""
    playlist: str = ""
    value: Optional[int] = None
    confidence: float = 1.0
    raw: str = ""


@dataclass(frozen=True)
class PendingChoice:
    kind: str
    options: List[str]
    created_at: float


@dataclass(frozen=True)
class FollowupResult:
    action: str
    index: Optional[int] = None
    raw: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _after_wake(transcript: str) -> Optional[str]:
    match = WAKE_RE.search(transcript)
    if not match:
        return None
    return _normalize(transcript[match.end() :])


def _clean_playlist_name(text: str) -> str:
    text = _normalize(text)
    text = re.sub(r"\b(?:playlist|the|my)\b", "", text, flags=re.IGNORECASE)
    return _normalize(text).lower()


def parse_command(transcript: str) -> ParsedCommand:
    raw = _normalize(transcript)
    command = _after_wake(raw)
    if not command:
        return ParsedCommand(intent="ignore", confidence=0.0, raw=raw)

    lowered = command.lower()

    if lowered in ("radio status", "station status"):
        return ParsedCommand(intent="station_status", raw=raw)

    if lowered.startswith("radio "):
        query = _normalize(command[len("radio ") :])
        return ParsedCommand(intent="start_radio", query=query, confidence=0.95, raw=raw)

    if lowered.startswith("play playlist "):
        playlist = _clean_playlist_name(command[len("play playlist ") :])
        return ParsedCommand(intent="play_playlist", playlist=playlist, raw=raw)
    if lowered.startswith("shuffle "):
        playlist = _clean_playlist_name(command[len("shuffle ") :])
        return ParsedCommand(intent="shuffle_playlist", playlist=playlist, raw=raw)
    if lowered.startswith("play "):
        query = _normalize(command[len("play ") :])
        return ParsedCommand(intent="play", query=query, confidence=0.95, raw=raw)

    save_match = re.match(
        r"save\s+(?:the\s+)?(?:(last|current|this)\s+)?(?:song|track|one)?\s*to\s+(.+)",
        lowered,
        flags=re.IGNORECASE,
    )
    if save_match:
        target = save_match.group(1) or "this"
        playlist = _clean_playlist_name(save_match.group(2))
        intent = "save_last_to_playlist" if target == "last" else "save_current_to_playlist"
        return ParsedCommand(intent=intent, playlist=playlist, raw=raw)

    volume_match = re.search(r"\bvolume\s+(\d{1,3})\b", lowered)
    if volume_match:
        value = max(0, min(100, int(volume_match.group(1))))
        return ParsedCommand(intent="volume", value=value, raw=raw)

    phrase_intents = [
        (("don't play this again", "do not play this again", "ban this", "never play this"), "station_ban_current"),
        (("more like this",), "station_more_like_current"),
        (("less like this",), "station_less_like_current"),
        (
            ("i don't like this", "don't like this", "i do not like this", "do not like this"),
            "unknown",
        ),
        (("like this", "i like this"), "station_like_current"),
        (("station status", "radio status"), "station_status"),
        (("skip", "next"), "skip"),
        (("pause",), "pause"),
        (("resume", "unpause"), "resume"),
        (("stop",), "stop"),
        (("clear queue",), "clear_queue"),
        (("queue", "what's next", "what is next"), "queue"),
        (("now playing", "what's playing", "what is playing"), "now"),
        (("disconnect", "leave"), "disconnect"),
        (("replay", "restart this"), "replay"),
        (("remove this", "delete this"), "remove_current"),
        (("louder", "turn it up"), "volume_up"),
        (("quieter", "lower", "turn it down"), "volume_down"),
        (("cancel", "never mind"), "cancel"),
    ]
    for phrases, intent in phrase_intents:
        if any(phrase in lowered for phrase in phrases):
            return ParsedCommand(intent=intent, raw=raw)

    return ParsedCommand(intent="unknown", query=command, confidence=0.35, raw=raw)


def _choice_index(text: str) -> Optional[int]:
    digit_match = re.search(r"\b(?:number|option|pick|play)?\s*([1-4])\b", text)
    if digit_match:
        return int(digit_match.group(1)) - 1
    for word, value in NUMBER_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return value - 1
    return None


def parse_followup(transcript: str, pending: PendingChoice, *, now: float) -> FollowupResult:
    raw = _normalize(transcript)
    lowered = raw.lower()
    if now - pending.created_at > CHOICE_TIMEOUT_SECONDS:
        return FollowupResult(action="expired", raw=raw)
    if any(phrase in lowered for phrase in ("neither", "none", "nope", "try again", "search again")):
        return FollowupResult(action="neither", raw=raw)
    if any(phrase in lowered for phrase in ("cancel", "never mind", "forget it")):
        return FollowupResult(action="cancel", raw=raw)

    index = _choice_index(lowered)
    if index is not None and 0 <= index < len(pending.options):
        return FollowupResult(action="choose", index=index, raw=raw)

    return FollowupResult(action="unknown", raw=raw)
