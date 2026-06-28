from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RECENT_LIMIT = 50
FEEDBACK_BUCKETS = {"liked", "banned", "more_like", "less_like", "skipped"}


def normalize_station_seed(seed: str) -> str:
    return re.sub(r"\s+", " ", seed.strip().lower())


def station_id(seed: str) -> str:
    return normalize_station_seed(seed)


def display_station_name(seed: str) -> str:
    cleaned = normalize_station_seed(seed).title()
    return f"{cleaned} radio"


def track_key(track: Dict[str, Any]) -> str:
    uri = str(track.get("uri", "")).strip()
    if uri:
        return f"uri:{uri}"
    title = re.sub(r"\s+", " ", str(track.get("title", "")).strip().lower())
    return f"title:{title}"


class DjGooStations:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._empty_store()
        with self.path.open(encoding="utf-8") as fp:
            try:
                data = json.load(fp)
            except json.JSONDecodeError:
                return self._empty_store()
        if not isinstance(data, dict) or not isinstance(data.get("stations"), dict):
            return self._empty_store()
        if not isinstance(data.get("active"), dict):
            data["active"] = {}
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=True)
            fp.write("\n")
        temp_path.replace(self.path)

    def get_or_create(self, seed: str) -> Dict[str, Any]:
        data = self._read()
        stations = data["stations"]
        identifier = station_id(seed)
        station = stations.get(identifier)
        if station is None:
            now = self._now()
            station = {
                "id": identifier,
                "name": display_station_name(seed),
                "seed": self._clean_seed(seed),
                "created_at": now,
                "updated_at": now,
                "played": [],
                "recent": [],
                "liked": [],
                "banned": [],
                "more_like": [],
                "less_like": [],
                "skipped": [],
                "last_track": None,
            }
            stations[identifier] = station
            self._write(data)
        return station

    def get_station(self, seed: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        return station if isinstance(station, dict) else None

    def set_active(self, guild_id: int, seed: str) -> Dict[str, Any]:
        station = self.get_or_create(seed)
        data = self._read()
        data["active"][str(guild_id)] = station["id"]
        self._write(data)
        return station

    def get_active(self, guild_id: int) -> Optional[Dict[str, Any]]:
        data = self._read()
        active = str(data.get("active", {}).get(str(guild_id), ""))
        station = data["stations"].get(active)
        return station if isinstance(station, dict) else None

    def active_guild_ids(self) -> List[int]:
        data = self._read()
        guild_ids = []
        for guild_id in data.get("active", {}):
            try:
                guild_ids.append(int(guild_id))
            except (TypeError, ValueError):
                continue
        return guild_ids

    def clear_active(self, guild_id: int) -> None:
        data = self._read()
        data["active"].pop(str(guild_id), None)
        self._write(data)

    def clear_all_active(self) -> None:
        data = self._read()
        data["active"] = {}
        self._write(data)

    def add_feedback(self, seed: str, feedback_type: str, track: Dict[str, Any]) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        station = self.get_or_create(seed)
        data = self._read()
        station = data["stations"][station["id"]]
        tracks = station.setdefault(feedback_type, [])
        cleaned = self._clean_track(track)
        if track_key(cleaned) not in {track_key(existing) for existing in tracks if isinstance(existing, dict)}:
            tracks.append(cleaned)
            station["updated_at"] = self._now()
        self._write(data)
        return station

    def mark_played(self, seed: str, track: Dict[str, Any]) -> Dict[str, Any]:
        station = self.get_or_create(seed)
        data = self._read()
        station = data["stations"][station["id"]]
        cleaned = self._clean_track(track)
        played = station.setdefault("played", [])
        recent = station.setdefault("recent", [])
        played.append(cleaned)
        recent.append(cleaned)
        del recent[:-RECENT_LIMIT]
        station["last_track"] = cleaned
        station["updated_at"] = self._now()
        self._write(data)
        return station

    def pick_candidate(
        self,
        seed: str,
        candidates: List[Dict[str, Any]],
        rng_seed: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        station = self.get_or_create(seed)
        banned = {track_key(track) for track in station.get("banned", []) if isinstance(track, dict)}
        recent = {track_key(track) for track in station.get("recent", []) if isinstance(track, dict)}
        available = [
            track
            for track in candidates
            if isinstance(track, dict) and track_key(track) not in banned and track_key(track) not in recent
        ]
        if not available:
            return None
        rng = random.Random(rng_seed)
        return rng.choice(available)

    def _clean_track(self, track: Dict[str, Any]) -> Dict[str, str]:
        return {
            "title": str(track.get("title", "")).strip(),
            "uri": str(track.get("uri", "")).strip(),
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _clean_seed(self, seed: str) -> str:
        return re.sub(r"\s+", " ", seed.strip())

    def _empty_store(self) -> Dict[str, Any]:
        return {"active": {}, "stations": {}}
