from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


WAKE_AT_START_RE = re.compile(
    r"^\s*(?:(?:hey|yo|okay|ok)\s+)?(?:dj\s*(?:goo|koo|goon)|djgoo|dee\s*jay|d\s*j|dj)\b[:,]?\s*",
    re.IGNORECASE,
)
WAKE_EARLY_RE = re.compile(
    r"^\s*(?:(?:hey|yo|okay|ok|so|alright|all right|please|can you|could you)[\s,]+){0,4}"
    r"(?:dj\s*(?:goo|koo|goon)|djgoo|dee\s*jay|d\s*j)\b[:,]?\s*",
    re.IGNORECASE,
)
NUMBER_WORDS = [
    ("first", 1),
    ("second", 2),
    ("third", 3),
    ("fourth", 4),
    ("fifth", 5),
    ("sixth", 6),
    ("seventh", 7),
    ("eighth", 8),
    ("ninth", 9),
    ("tenth", 10),
    ("one", 1),
    ("two", 2),
    ("three", 3),
    ("four", 4),
    ("five", 5),
    ("six", 6),
    ("seven", 7),
    ("eight", 8),
    ("nine", 9),
    ("ten", 10),
]
CARDINAL_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
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


def _command_key(text: str) -> str:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    words = text.split()
    if len(words) >= 2 and len(set(words)) == 1:
        words = words[:1]
    return " ".join(words)


def _after_wake(transcript: str) -> Optional[str]:
    match = WAKE_AT_START_RE.search(transcript) or WAKE_EARLY_RE.search(transcript)
    if not match:
        return None
    command = _normalize(transcript[match.end() :])
    command = re.sub(r"^[\s\W_]+|[\s\W_]+$", "", command)
    return command


def _clean_playlist_name(text: str) -> str:
    text = _normalize(text)
    text = re.sub(r"\b(?:playlist|the|my)\b", "", text, flags=re.IGNORECASE)
    return _normalize(text).lower()


def _matches_command_phrase(command: str, phrase: str) -> bool:
    return command == phrase or command.startswith(f"{phrase} ")


def _word_number(text: str) -> Optional[int]:
    words = re.findall(r"[a-z]+", text.lower())
    total = 0
    found = False
    for word in words:
        if word not in CARDINAL_WORDS:
            continue
        total += CARDINAL_WORDS[word]
        found = True
    return total if found else None


def _parse_time_seconds(text: str) -> Optional[int]:
    colon = re.search(r"\b(\d{1,2}):(\d{1,2})\b", text)
    if colon:
        return int(colon.group(1)) * 60 + int(colon.group(2))
    hours = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\b", text)
    minutes = re.search(r"\b(\d+)\s*(?:minutes?|mins?)\b", text)
    seconds = re.search(r"\b(\d+)\s*(?:seconds?|secs?)\b", text)
    total = 0
    if hours:
        total += int(hours.group(1)) * 3600
    if minutes:
        total += int(minutes.group(1)) * 60
    if seconds:
        total += int(seconds.group(1))
    if total:
        return total
    word_value = _word_number(text)
    if word_value is not None:
        if re.search(r"\b(?:minutes?|mins?)\b", text, re.IGNORECASE):
            return word_value * 60
        if re.search(r"\b(?:seconds?|secs?)\b", text, re.IGNORECASE):
            return word_value
    plain = re.search(r"\b(\d{1,5})\b", text)
    return int(plain.group(1)) if plain else None


def _queue_position(text: str) -> Optional[int]:
    digit = re.search(
        r"\b(?:number|item|track|song|position)?\s*(\d{1,3})\b",
        text,
    )
    if digit:
        return int(digit.group(1))
    lowered = text.lower()
    for word, value in NUMBER_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return value
    return None


def _request_query(command: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.match(pattern, command, flags=re.IGNORECASE)
        if match:
            return _normalize(match.group(1))
    return ""


def parse_command(transcript: str, *, require_wake: bool = True) -> ParsedCommand:
    raw = _normalize(transcript)
    command = _after_wake(raw) if require_wake else _normalize(raw)
    if not require_wake:
        command = re.sub(r"^[\s\W_]+|[\s\W_]+$", "", command)
    if not command:
        return ParsedCommand(intent="ignore", confidence=0.0, raw=raw)

    lowered = _command_key(command)

    seek_match = re.match(
        r"^(?:seek|go to|jump to|skip to)\s+(.+)$",
        command,
        re.IGNORECASE,
    )
    if seek_match:
        seconds = _parse_time_seconds(seek_match.group(1))
        if seconds is not None:
            return ParsedCommand(
                intent="seek",
                value=seconds,
                confidence=0.98,
                raw=raw,
            )

    remove_match = re.match(
        r"^(?:remove|delete)\s+(?:queue\s+)?(?:number\s+|item\s+|track\s+|song\s+)?(.+?)(?:\s+from\s+(?:the\s+)?queue)?$",
        command,
        re.IGNORECASE,
    )
    if remove_match and lowered not in {"remove this", "delete this"}:
        position = _queue_position(remove_match.group(1))
        if position is not None:
            return ParsedCommand(
                intent="remove_queue",
                value=position,
                confidence=0.98,
                raw=raw,
            )

    if lowered in ("radio status", "station status"):
        return ParsedCommand(intent="station_status", raw=raw)
    if lowered in (
        "stop radio",
        "radio off",
        "end radio",
        "turn off radio",
        "quit radio",
    ):
        return ParsedCommand(intent="stop_radio", raw=raw)
    if lowered.startswith("radio "):
        query = _normalize(command[len("radio ") :])
        if query.lower() in ("off", "stop", "end"):
            return ParsedCommand(intent="stop_radio", raw=raw)
        return ParsedCommand(
            intent="start_radio",
            query=query,
            confidence=0.95,
            raw=raw,
        )

    if lowered.startswith("play playlist "):
        playlist = _clean_playlist_name(command[len("play playlist ") :])
        return ParsedCommand(intent="play_playlist", playlist=playlist, raw=raw)
    if lowered.startswith("play album "):
        query = _normalize(command[len("play album ") :])
        return ParsedCommand(
            intent="play_album",
            query=query,
            confidence=0.95,
            raw=raw,
        )
    if lowered.startswith("shuffle ") and lowered not in {
        "shuffle queue",
        "shuffle the queue",
    }:
        playlist = _clean_playlist_name(command[len("shuffle ") :])
        return ParsedCommand(intent="shuffle_playlist", playlist=playlist, raw=raw)

    play_now_query = _request_query(
        command,
        (
            r"^(?:play|request)\s+now\s+(.+)$",
            r"^(?:interrupt(?:\s+this)?\s+with|play\s+immediately)\s+(.+)$",
        ),
    )
    if play_now_query:
        return ParsedCommand(
            intent="play_now",
            query=play_now_query,
            confidence=0.98,
            raw=raw,
        )

    queue_request_query = _request_query(
        command,
        (
            r"^(?:queue\s+(?:a\s+)?request|add\s+(?:a\s+)?request)\s+(.+)$",
            r"^(?:request|play)\s+later\s+(.+)$",
        ),
    )
    if queue_request_query:
        return ParsedCommand(
            intent="queue_request",
            query=queue_request_query,
            confidence=0.98,
            raw=raw,
        )

    play_next_query = _request_query(
        command,
        (
            r"^(?:play|request)\s+next\s+(.+)$",
            r"^request\s+(.+)$",
        ),
    )
    if play_next_query:
        return ParsedCommand(
            intent="play",
            query=play_next_query,
            confidence=0.97,
            raw=raw,
        )

    play_alias = re.match(
        r"^(?:play|ice)\s+(.+)$",
        command,
        flags=re.IGNORECASE,
    )
    if play_alias:
        query = _normalize(play_alias.group(1))
        return ParsedCommand(
            intent="play",
            query=query,
            confidence=0.95,
            raw=raw,
        )

    save_match = re.match(
        r"save\s+(?:the\s+)?(?:(last|current|this)\s+)?(?:song|track|one)?\s*to\s+(.+)",
        lowered,
        flags=re.IGNORECASE,
    )
    if save_match:
        target = save_match.group(1) or "this"
        playlist = _clean_playlist_name(save_match.group(2))
        intent = (
            "save_last_to_playlist"
            if target == "last"
            else "save_current_to_playlist"
        )
        return ParsedCommand(intent=intent, playlist=playlist, raw=raw)

    volume_match = re.search(r"\bvolume\s+(\d{1,3})\b", lowered)
    if volume_match:
        value = max(0, min(100, int(volume_match.group(1))))
        return ParsedCommand(intent="volume", value=value, raw=raw)

    phrase_intents = [
        (
            (
                "don't play this again",
                "do not play this again",
                "ban this",
                "never play this",
            ),
            "station_ban_current",
        ),
        (("undo ban", "undo last ban", "allow that again"), "undo_station_ban"),
        (("undo", "undo that", "put it back", "take that back"), "gaming_undo"),
        (("more like this",), "station_more_like_current"),
        (("less like this",), "station_less_like_current"),
        (
            (
                "i don't like this",
                "don't like this",
                "i do not like this",
                "do not like this",
            ),
            "station_less_like_current",
        ),
        (("like this", "i like this"), "station_like_current"),
        (
            ("favorite this", "save this", "add to favorites", "favorite current"),
            "favorite_current",
        ),
        (("shuffle queue", "shuffle the queue"), "shuffle_queue"),
        (("repeat", "toggle repeat", "repeat mode"), "repeat"),
        (("autoplay", "toggle autoplay", "auto play"), "autoplay"),
        (("station status", "radio status"), "station_status"),
        (
            ("stop radio", "radio off", "end radio", "turn off radio", "quit radio"),
            "stop_radio",
        ),
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
        if any(_matches_command_phrase(lowered, phrase) for phrase in phrases):
            return ParsedCommand(intent=intent, raw=raw)

    return ParsedCommand(
        intent="unknown",
        query=command,
        confidence=0.35,
        raw=raw,
    )


def parse_emergency_control(transcript: str) -> ParsedCommand:
    raw = _normalize(transcript)
    lowered = re.sub(r"^[\s\W_]+|[\s\W_]+$", "", raw.lower())
    patterns = [
        (r"^(skip|next)(?:\s+(it|this|song|track|please))?$", "skip"),
        (r"^stop(?:\s+(music|song|track|please))?$", "stop"),
        (r"^pause(?:\s+(music|song|track|please))?$", "pause"),
        (r"^(resume|unpause)(?:\s+(music|song|track|please))?$", "resume"),
        (r"^(queue|what's next|what is next)$", "queue"),
        (r"^(now|now playing|what's playing|what is playing)$", "now"),
    ]
    for pattern, intent in patterns:
        if re.match(pattern, lowered):
            return ParsedCommand(intent=intent, confidence=0.8, raw=raw)
    return ParsedCommand(intent="ignore", confidence=0.0, raw=raw)


def _choice_index(text: str) -> Optional[int]:
    digit_match = re.search(
        r"\b(?:number|option|pick|play)?\s*([1-4])\b",
        text,
    )
    if digit_match:
        return int(digit_match.group(1)) - 1
    for word, value in NUMBER_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return value - 1
    return None


def parse_followup(
    transcript: str,
    pending: PendingChoice,
    *,
    now: float,
) -> FollowupResult:
    raw = _normalize(transcript)
    lowered = raw.lower()
    if now - pending.created_at > CHOICE_TIMEOUT_SECONDS:
        return FollowupResult(action="expired", raw=raw)
    if any(
        phrase in lowered
        for phrase in ("neither", "none", "nope", "try again", "search again")
    ):
        return FollowupResult(action="neither", raw=raw)
    if any(
        phrase in lowered
        for phrase in ("cancel", "never mind", "forget it")
    ):
        return FollowupResult(action="cancel", raw=raw)
    index = _choice_index(lowered)
    if index is not None and 0 <= index < len(pending.options):
        return FollowupResult(action="choose", index=index, raw=raw)
    return FollowupResult(action="unknown", raw=raw)
