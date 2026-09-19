from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class PlaylistAddResult:
    playlist_name: str
    added: bool
    track_count: int


def normalize_playlist_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    normalized = re.sub(r"\b(?:playlist|the|my)\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:48]


def playlist_track_id(track: Dict[str, Any]) -> str:
    existing = str(track.get("id") or "").strip()
    if existing:
        return existing
    identity = str(track.get("uri") or "").strip().lower()
    if not identity:
        identity = "|".join(
            (
                str(track.get("title") or "").strip().lower(),
                str(track.get("artist") or "").strip().lower(),
            )
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


class DjGooPlaylists:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"playlists": {}}
        with self.path.open(encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict) or not isinstance(data.get("playlists"), dict):
            return {"playlists": {}}
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=True)
            fp.write("\n")
        temporary.replace(self.path)

    def _match_name(self, requested_name: str, playlists: Dict[str, Any]) -> str:
        requested = normalize_playlist_name(requested_name)
        if requested in playlists:
            return requested
        best_name = ""
        best_score = 0.0
        for existing in playlists:
            score = SequenceMatcher(None, requested, existing).ratio()
            if requested and (requested in existing or existing in requested):
                score = max(score, 0.88)
            if score > best_score:
                best_name = existing
                best_score = score
        return best_name if best_score >= 0.74 else requested

    def add_track(self, playlist_name: str, track: Dict[str, Any]) -> PlaylistAddResult:
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched_name = self._match_name(playlist_name, playlists)
            playlist = playlists.setdefault(matched_name, {"tracks": []})
            tracks = playlist.setdefault("tracks", [])
            uri = str(track.get("uri", "")).strip()
            title = str(track.get("title", "")).strip()

            for existing in tracks:
                if uri and uri == str(existing.get("uri", "")).strip():
                    return PlaylistAddResult(matched_name, False, len(tracks))
                if not uri and title and title.lower() == str(existing.get("title", "")).lower():
                    return PlaylistAddResult(matched_name, False, len(tracks))

            tracks.append(
                {
                    "id": playlist_track_id(track),
                    "title": title,
                    "artist": str(track.get("artist", "")).strip(),
                    "uri": uri,
                    "artwork_url": str(track.get("artwork_url", "")).strip(),
                    "duration_seconds": int(track.get("duration_seconds") or 0),
                }
            )
            self._write(data)
            return PlaylistAddResult(matched_name, True, len(tracks))

    def get_tracks(self, playlist_name: str) -> List[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched_name = self._match_name(playlist_name, playlists)
            playlist = playlists.get(matched_name, {})
            tracks = playlist.get("tracks", [])
            return [
                {**dict(track), "id": playlist_track_id(track)}
                for track in tracks
                if isinstance(track, dict)
            ]

    def create(self, playlist_name: str) -> tuple[str, bool]:
        requested = normalize_playlist_name(playlist_name)
        if not requested:
            raise ValueError("Playlist name is required")
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched = self._match_name(requested, playlists)
            if matched in playlists:
                return matched, False
            playlists[requested] = {"tracks": []}
            self._write(data)
            return requested, True

    def rename(self, playlist_name: str, new_name: str) -> tuple[str, str]:
        requested = normalize_playlist_name(new_name)
        if not requested:
            raise ValueError("New playlist name is required")
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched = self._match_name(playlist_name, playlists)
            if matched not in playlists:
                raise ValueError(f"Playlist not found: {playlist_name}")
            if requested != matched and requested in playlists:
                raise ValueError(f"Playlist already exists: {requested}")
            value = playlists.pop(matched)
            playlists[requested] = value
            self._write(data)
            return matched, requested

    def delete(self, playlist_name: str) -> str:
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched = self._match_name(playlist_name, playlists)
            if matched not in playlists:
                raise ValueError(f"Playlist not found: {playlist_name}")
            playlists.pop(matched)
            self._write(data)
            return matched

    def remove_tracks(self, playlist_name: str, track_ids: List[str]) -> tuple[str, int]:
        selected = {str(value) for value in track_ids if str(value).strip()}
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched = self._match_name(playlist_name, playlists)
            if matched not in playlists:
                raise ValueError(f"Playlist not found: {playlist_name}")
            tracks = playlists[matched].setdefault("tracks", [])
            retained = [
                track
                for track in tracks
                if not isinstance(track, dict) or playlist_track_id(track) not in selected
            ]
            removed = len(tracks) - len(retained)
            playlists[matched]["tracks"] = retained
            self._write(data)
            return matched, removed

    def reorder_tracks(self, playlist_name: str, track_ids: List[str]) -> str:
        ordered_ids = [str(value) for value in track_ids if str(value).strip()]
        with self._lock:
            data = self._read()
            playlists = data["playlists"]
            matched = self._match_name(playlist_name, playlists)
            if matched not in playlists:
                raise ValueError(f"Playlist not found: {playlist_name}")
            tracks = [
                track
                for track in playlists[matched].setdefault("tracks", [])
                if isinstance(track, dict)
            ]
            by_id = {playlist_track_id(track): track for track in tracks}
            if len(ordered_ids) != len(tracks) or set(ordered_ids) != set(by_id):
                raise ValueError("The playlist changed before its order was saved")
            playlists[matched]["tracks"] = [by_id[track_id] for track_id in ordered_ids]
            self._write(data)
            return matched

    def summaries(self) -> List[Dict[str, Any]]:
        with self._lock:
            playlists = self._read().get("playlists", {})
            if not isinstance(playlists, dict):
                return []
            return [
                {
                    "name": str(name),
                    "track_count": len(
                        [track for track in data.get("tracks", []) if isinstance(track, dict)]
                    ),
                    "tracks": [
                        {**dict(track), "id": playlist_track_id(track)}
                        for track in data.get("tracks", [])
                        if isinstance(track, dict)
                    ],
                }
                for name, data in sorted(playlists.items())
                if isinstance(data, dict)
            ]
