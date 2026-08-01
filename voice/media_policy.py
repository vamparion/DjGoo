from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


MAX_TRACK_SECONDS = 10 * 60
BAD_TITLE_PHRASES = (
    "instrumental",
    "karaoke",
    "reaction",
    "interview",
    "lesson",
    "tutorial",
    "documentary",
    "behind the scenes",
    "making of",
    "shorts",
    "clip",
    "compilation",
    "collection",
    "playlist",
    "full album",
    "greatest hits",
    "dj set",
    "hour of",
    "hours of",
    "live at",
    "live from",
    "live in",
    "extended version",
    "extended mix",
    "loop",
    "repeat",
)


@dataclass(frozen=True)
class CanonicalTrack:
    title: str
    artists: tuple[str, ...]
    duration_seconds: int = 0
    isrc: str = ""


@dataclass(frozen=True)
class MediaCandidate:
    title: str
    artists: tuple[str, ...]
    uri: str
    duration_seconds: int = 0
    channel: str = ""
    result_index: int = 0

    @property
    def display_title(self) -> str:
        artist = ", ".join(self.artists)
        return f"{artist} - {self.title}" if artist else self.title


def normalize_words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def title_is_rejected(title: str) -> bool:
    normalized = f" {normalize_words(title)} "
    if re.search(r"\b\d+\s*(?:hour|hours|hr|hrs)\b", normalized):
        return True
    if re.search(r"\b(?:full\s+)?album\b", normalized):
        return True
    return any(f" {normalize_words(phrase)} " in normalized for phrase in BAD_TITLE_PHRASES)


def duration_tolerance(canonical_seconds: int) -> int:
    if canonical_seconds <= 0:
        return 30
    return max(18, min(45, round(canonical_seconds * 0.08)))


def duration_is_plausible(candidate_seconds: int, canonical_seconds: int = 0) -> bool:
    if candidate_seconds <= 0:
        return True
    if candidate_seconds > MAX_TRACK_SECONDS:
        return False
    if canonical_seconds <= 0:
        return True
    tolerance = duration_tolerance(canonical_seconds)
    return abs(candidate_seconds - canonical_seconds) <= tolerance


def artist_similarity(candidate_artists: Sequence[str], canonical_artists: Sequence[str]) -> float:
    if not canonical_artists:
        return 1.0
    candidate_tokens = {normalize_words(artist) for artist in candidate_artists if normalize_words(artist)}
    canonical_tokens = {normalize_words(artist) for artist in canonical_artists if normalize_words(artist)}
    if not candidate_tokens or not canonical_tokens:
        return 0.0
    if candidate_tokens & canonical_tokens:
        return 1.0
    candidate_words = set(" ".join(candidate_tokens).split())
    canonical_words = set(" ".join(canonical_tokens).split())
    union = candidate_words | canonical_words
    return len(candidate_words & canonical_words) / len(union) if union else 0.0


def title_similarity(candidate_title: str, canonical_title: str) -> float:
    if not canonical_title:
        return 1.0
    candidate = set(normalize_words(candidate_title).split())
    canonical = set(normalize_words(canonical_title).split())
    if not candidate or not canonical:
        return 0.0
    return len(candidate & canonical) / len(candidate | canonical)


def score_search_candidate(candidate: MediaCandidate, canonical: CanonicalTrack | None) -> float:
    if not candidate.uri or not candidate.title or title_is_rejected(candidate.display_title):
        return float("-inf")
    canonical_duration = canonical.duration_seconds if canonical else 0
    if not duration_is_plausible(candidate.duration_seconds, canonical_duration):
        return float("-inf")

    score = 100.0 - min(35.0, candidate.result_index * 4.0)
    title_text = normalize_words(candidate.title)
    channel_text = normalize_words(candidate.channel)
    full_text = f" {normalize_words(candidate.display_title)} "

    if "official audio" in title_text:
        score += 34
    if "official music video" in title_text or "official video" in title_text:
        score += 22
    if channel_text.endswith(" topic") or " topic " in f" {channel_text} ":
        score += 30
    if "lyrics" in title_text or "lyric video" in title_text:
        score += 5
    if "remaster" in full_text:
        score -= 3

    if canonical:
        score += 55 * title_similarity(candidate.title, canonical.title)
        score += 45 * artist_similarity(candidate.artists, canonical.artists)
        if canonical.duration_seconds and candidate.duration_seconds:
            score -= abs(candidate.duration_seconds - canonical.duration_seconds) * 1.3
    return score


def pick_best_search_candidate(
    candidates: Sequence[MediaCandidate],
    canonical: CanonicalTrack | None,
) -> MediaCandidate | None:
    scored = [(score_search_candidate(candidate, canonical), candidate) for candidate in candidates]
    scored = [item for item in scored if math.isfinite(item[0])]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def track_identity(track: Mapping[str, Any]) -> str:
    uri = str(track.get("uri", "")).strip()
    if uri:
        return f"uri:{uri}"
    return f"title:{normalize_words(str(track.get('title', '')))}"


def track_artist(track: Mapping[str, Any]) -> str:
    artist = str(track.get("artist", "")).strip()
    if artist:
        return normalize_words(artist)
    title = str(track.get("title", ""))
    if " - " in title:
        return normalize_words(title.split(" - ", 1)[0])
    return ""


def score_radio_candidate(candidate: MediaCandidate, station: Mapping[str, Any]) -> float:
    if title_is_rejected(candidate.display_title) or not duration_is_plausible(candidate.duration_seconds):
        return float("-inf")
    candidate_data = {
        "title": candidate.display_title,
        "artist": ", ".join(candidate.artists),
        "uri": candidate.uri,
        "duration_seconds": candidate.duration_seconds,
    }
    identity = track_identity(candidate_data)
    banned = {
        track_identity(track)
        for track in station.get("banned", [])
        if isinstance(track, Mapping)
    }
    recent = [track for track in station.get("recent", []) if isinstance(track, Mapping)]
    if identity in banned or identity in {track_identity(track) for track in recent}:
        return float("-inf")

    score = 100.0 - min(25.0, candidate.result_index * 2.0)
    artist = track_artist(candidate_data)
    recent_artists = [track_artist(track) for track in recent[-6:]]
    if artist and artist in recent_artists:
        score -= 42
    if artist and recent_artists and artist == recent_artists[-1]:
        score -= 65

    for bucket, weight in (("liked", 22), ("more_like", 30), ("less_like", -38), ("skipped", -15)):
        for feedback in station.get(bucket, []):
            if not isinstance(feedback, Mapping):
                continue
            feedback_artist = track_artist(feedback)
            if artist and feedback_artist and artist == feedback_artist:
                score += weight
            feedback_title = normalize_words(str(feedback.get("title", "")))
            if feedback_title and title_similarity(candidate.display_title, feedback_title) > 0.55:
                score += weight * 0.5

    normalized_title = normalize_words(candidate.title)
    normalized_channel = normalize_words(candidate.channel)
    if "official audio" in normalized_title:
        score += 18
    if normalized_channel.endswith(" topic"):
        score += 16
    return score


def pick_radio_candidate(
    candidates: Sequence[MediaCandidate],
    station: Mapping[str, Any],
    *,
    rng: random.Random | None = None,
) -> MediaCandidate | None:
    scored = [(score_radio_candidate(candidate, station), candidate) for candidate in candidates]
    scored = [item for item in scored if math.isfinite(item[0])]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    shortlist = scored[: min(5, len(scored))]
    floor = shortlist[-1][0]
    weights = [max(1.0, score - floor + 1.0) ** 1.4 for score, _ in shortlist]
    chooser = rng or random
    return chooser.choices([candidate for _, candidate in shortlist], weights=weights, k=1)[0]


def candidates_from_ytmusic(items: Iterable[Mapping[str, Any]]) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    for index, item in enumerate(items):
        video_id = str(item.get("videoId") or "").strip()
        title = str(item.get("title") or "").strip()
        if not video_id or not title:
            continue
        artists = tuple(
            str(artist.get("name", "")).strip()
            for artist in item.get("artists", [])
            if isinstance(artist, Mapping) and str(artist.get("name", "")).strip()
        )
        duration_text = str(item.get("duration") or item.get("length") or "")
        duration = parse_duration(duration_text)
        channel = str(item.get("channel") or item.get("author") or "").strip()
        candidates.append(
            MediaCandidate(
                title=title,
                artists=artists,
                uri=f"https://www.youtube.com/watch?v={video_id}",
                duration_seconds=duration,
                channel=channel,
                result_index=index,
            )
        )
    return candidates


def parse_duration(value: str) -> int:
    text = value.strip()
    if not text:
        return 0
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return 0
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0
