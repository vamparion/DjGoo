from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandHint:
    phrase: str
    description: str
    category: str
    requires_radio: bool = False


COMMAND_HINTS: tuple[CommandHint, ...] = (
    CommandHint(
        "play next Sandstorm",
        "Play one request after the current song, then return to radio",
        "Requests",
    ),
    CommandHint(
        "play now Sandstorm",
        "Interrupt with one request, then return to radio",
        "Requests",
    ),
    CommandHint(
        "queue request Sandstorm",
        "Place a request after existing player requests but before radio",
        "Requests",
    ),
    CommandHint(
        "radio balanced 2000s rock",
        "Start a continuous station",
        "Radio",
    ),
    CommandHint("skip", "Skip the current song", "Playback"),
    CommandHint("pause", "Pause playback", "Playback"),
    CommandHint("resume", "Resume playback", "Playback"),
    CommandHint(
        "what is playing",
        "Hear or display the current song",
        "Playback",
    ),
    CommandHint(
        "what is next",
        "Show the request and radio queue",
        "Queue",
    ),
    CommandHint(
        "remove number three",
        "Remove a queued song by position",
        "Queue",
    ),
    CommandHint(
        "shuffle the queue",
        "Shuffle queued requests",
        "Queue",
    ),
    CommandHint("volume 45", "Set DjGoo volume", "Playback"),
    CommandHint(
        "like this",
        "Teach the active station",
        "Radio",
        True,
    ),
    CommandHint(
        "more like this",
        "Steer the station toward this song",
        "Radio",
        True,
    ),
    CommandHint(
        "less like this",
        "Steer the station away from this song",
        "Radio",
        True,
    ),
    CommandHint(
        "don't play this again",
        "Permanently block this song on the station",
        "Radio",
        True,
    ),
    CommandHint(
        "undo last ban",
        "Allow the last blocked song again",
        "Radio",
        True,
    ),
    CommandHint(
        "add to favorites",
        "Save the current song",
        "Library",
    ),
    CommandHint(
        "seek 1:30",
        "Jump to a position in the song",
        "Playback",
    ),
    CommandHint(
        "stop radio",
        "Stop the station and its automatic queue",
        "Radio",
        True,
    ),
)


def command_hints(
    *,
    radio_active: bool | None = None,
) -> tuple[CommandHint, ...]:
    if radio_active is None:
        return COMMAND_HINTS
    return tuple(
        hint
        for hint in COMMAND_HINTS
        if not hint.requires_radio or radio_active
    )


def command_tip(
    index: int,
    *,
    radio_active: bool | None = None,
) -> CommandHint:
    hints = command_hints(radio_active=radio_active)
    if not hints:
        return COMMAND_HINTS[0]
    return hints[int(index) % len(hints)]


def command_help_text(*, wake_word: str = "DjGoo") -> str:
    categories: dict[str, list[str]] = {}
    for hint in COMMAND_HINTS:
        categories.setdefault(hint.category, []).append(
            f"`{wake_word}, {hint.phrase}` — {hint.description}"
        )
    sections = []
    for category in (
        "Requests",
        "Playback",
        "Queue",
        "Radio",
        "Library",
    ):
        entries = categories.get(category)
        if entries:
            sections.append(f"**{category}**\n" + "\n".join(entries))
    return "\n\n".join(sections)
