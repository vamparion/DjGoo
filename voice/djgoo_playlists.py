from __future__ import annotations

import json
import re
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


class DjGooPlaylists:
    def __init__(self, path: Path):
        self.path = path

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
        with self.path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=True)
            fp.write("\n")

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

        tracks.append({"title": title, "uri": uri})
        self._write(data)
        return PlaylistAddResult(matched_name, True, len(tracks))

    def get_tracks(self, playlist_name: str) -> List[Dict[str, Any]]:
        data = self._read()
        playlists = data["playlists"]
        matched_name = self._match_name(playlist_name, playlists)
        playlist = playlists.get(matched_name, {})
        tracks = playlist.get("tracks", [])
        return [track for track in tracks if isinstance(track, dict)]
