from __future__ import annotations

from typing import Any, Iterable, Mapping

from voice.media_policy import track_identity


INTENTIONAL_MANUAL_SOURCES = {
    "chat",
    "discord",
    "voice",
    "voice_remote",
}


def allows_duplicate(source: str) -> bool:
    """Only an explicit player request may intentionally repeat a track."""

    return str(source).strip().lower() in INTENTIONAL_MANUAL_SOURCES


def filter_automatic_duplicates(
    tracks: Iterable[Mapping[str, Any]],
    *,
    existing_identities: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    seen = set(existing_identities or set())
    accepted: list[dict[str, Any]] = []
    skipped = 0
    for track in tracks:
        item = dict(track)
        identity = track_identity(item)
        source = str(item.get("source") or "automatic")
        if identity and identity in seen and not allows_duplicate(source):
            skipped += 1
            continue
        accepted.append(item)
        if identity:
            seen.add(identity)
    return accepted, skipped
