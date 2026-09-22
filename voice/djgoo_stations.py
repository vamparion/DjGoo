from __future__ import annotations

import json
import random
import re
import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RECENT_LIMIT = 50
FEEDBACK_BUCKETS = {"liked", "banned", "more_like", "less_like", "skipped"}
STATION_DEFAULTS = {
    "familiar_percent": 55,
    "discovery_percent": 20,
    "artist_spacing": 4,
    "song_spacing": 50,
    "seed_type": "auto",
    "seed_examples": [],
    "snapshots": [],
    "feedback_history": [],
}


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
                **copy.deepcopy(STATION_DEFAULTS),
            }
            stations[identifier] = station
            self._write(data)
        return self._normalize_station(station)

    def get_station(self, seed: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        return self._normalize_station(station) if isinstance(station, dict) else None

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
        return self._normalize_station(station) if isinstance(station, dict) else None

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
            station.setdefault("feedback_history", []).append({
                "id": uuid.uuid4().hex,
                "action": feedback_type,
                "track": cleaned,
                "created_at": self._now(),
            })
            del station["feedback_history"][:-500]
            station["updated_at"] = self._now()
        self._write(data)
        return station

    def undo_feedback(self, seed: str, feedback_type: str) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        data = self._read()
        identifier = station_id(seed)
        station = data["stations"].get(identifier)
        if not isinstance(station, dict):
            raise ValueError(f"Station not found: {seed}")
        history = station.setdefault("feedback_history", [])
        match = next((item for item in reversed(history) if item.get("action") == feedback_type), None)
        if match is None:
            raise ValueError(f"No recent {feedback_type.replace('_', ' ')} feedback to undo")
        key = track_key(match.get("track") or {})
        station[feedback_type] = [item for item in station.get(feedback_type, []) if track_key(item) != key]
        history.remove(match)
        station["updated_at"] = self._now()
        self._write(data)
        return self._normalize_station(station)

    def remove_feedback(self, seed: str, feedback_type: str, track: Dict[str, Any]) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        data = self._read()
        station = data["stations"].get(station_id(seed))
        if not isinstance(station, dict):
            raise ValueError(f"Station not found: {seed}")
        key = track_key(track)
        station[feedback_type] = [item for item in station.get(feedback_type, []) if not isinstance(item, dict) or track_key(item) != key]
        station["updated_at"] = self._now()
        self._write(data)
        return self._normalize_station(station)

    def set_selection_reason(self, seed: str, reason: str, *, drift_score: int = 0) -> None:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        if not isinstance(station, dict):
            return
        station["last_selection_reason"] = str(reason).strip()[:300]
        station["last_drift_score"] = max(0, min(100, int(drift_score)))
        self._write(data)

    def update_settings(self, seed: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        if not isinstance(station, dict):
            raise ValueError(f"Station not found: {seed}")
        for key in ("familiar_percent", "discovery_percent", "artist_spacing", "song_spacing"):
            if key in updates:
                station[key] = max(0, min(100 if "percent" in key else 200, int(updates[key])))
        for key in ("seed_type", "description"):
            if key in updates:
                station[key] = str(updates[key]).strip()[:500]
        if "seed_examples" in updates and isinstance(updates["seed_examples"], list):
            station["seed_examples"] = [str(value).strip()[:200] for value in updates["seed_examples"] if str(value).strip()][:20]
        station["updated_at"] = self._now()
        self._write(data)
        return self._normalize_station(station)

    def create_snapshot(self, seed: str, name: str = "") -> Dict[str, Any]:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        if not isinstance(station, dict):
            raise ValueError(f"Station not found: {seed}")
        snapshot = {
            "id": uuid.uuid4().hex,
            "name": str(name).strip()[:80] or f"Snapshot {len(station.get('snapshots', [])) + 1}",
            "created_at": self._now(),
            "state": {key: copy.deepcopy(value) for key, value in station.items() if key not in {"snapshots", "played", "recent", "last_track"}},
        }
        station.setdefault("snapshots", []).append(snapshot)
        del station["snapshots"][:-20]
        self._write(data)
        return snapshot

    def restore_snapshot(self, seed: str, snapshot_id: str) -> Dict[str, Any]:
        data = self._read()
        station = data["stations"].get(station_id(seed))
        if not isinstance(station, dict):
            raise ValueError(f"Station not found: {seed}")
        snapshot = next((item for item in station.get("snapshots", []) if str(item.get("id")) == str(snapshot_id)), None)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("state"), dict):
            raise ValueError("Station snapshot was not found")
        preserved = {key: station.get(key) for key in ("played", "recent", "last_track", "snapshots")}
        station.update(copy.deepcopy(snapshot["state"]))
        station.update(preserved)
        station["updated_at"] = self._now()
        self._write(data)
        return self._normalize_station(station)

    def clone(self, seed: str, new_seed: str) -> Dict[str, Any]:
        data = self._read()
        source = data["stations"].get(station_id(seed))
        identifier = station_id(new_seed)
        if not isinstance(source, dict):
            raise ValueError(f"Station not found: {seed}")
        if identifier in data["stations"]:
            raise ValueError(f"Station already exists: {new_seed}")
        clone = copy.deepcopy(source)
        clone.update({"id": identifier, "name": display_station_name(new_seed), "seed": self._clean_seed(new_seed), "created_at": self._now(), "updated_at": self._now(), "played": [], "recent": [], "last_track": None, "snapshots": []})
        data["stations"][identifier] = clone
        self._write(data)
        return self._normalize_station(clone)

    def merge(self, seeds: List[str], new_seed: str) -> Dict[str, Any]:
        sources = [self.get_station(seed) for seed in seeds]
        sources = [item for item in sources if item]
        if len(sources) < 2:
            raise ValueError("Choose at least two existing stations to merge")
        target = self.get_or_create(new_seed)
        data = self._read()
        merged = data["stations"][target["id"]]
        for bucket in FEEDBACK_BUCKETS:
            unique = {track_key(item): item for source in sources for item in source.get(bucket, []) if isinstance(item, dict)}
            merged[bucket] = list(unique.values())
        merged["seed_examples"] = list(dict.fromkeys([source.get("seed", "") for source in sources] + [example for source in sources for example in source.get("seed_examples", [])]))[:20]
        merged["played"], merged["recent"], merged["last_track"] = [], [], None
        merged["updated_at"] = self._now()
        self._write(data)
        return self._normalize_station(merged)

    def all_stations(self) -> List[Dict[str, Any]]:
        return [self._normalize_station(item) for item in self._read().get("stations", {}).values() if isinstance(item, dict)]

    def _normalize_station(self, station: Dict[str, Any]) -> Dict[str, Any]:
        result = copy.deepcopy(station)
        for key, value in STATION_DEFAULTS.items():
            result.setdefault(key, copy.deepcopy(value))
        return result

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

    def set_seed_track(self, seed: str, track: Dict[str, Any]) -> Dict[str, Any]:
        """Remember the exact seed without counting it as already played."""

        station = self.get_or_create(seed)
        data = self._read()
        station = data["stations"][station["id"]]
        station["seed_track"] = self._clean_track(track)
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
            "artist": str(track.get("artist", "")).strip(),
            "uri": str(track.get("uri", "")).strip(),
            "artwork_url": str(track.get("artwork_url", "")).strip(),
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _clean_seed(self, seed: str) -> str:
        return re.sub(r"\s+", " ", seed.strip())

    def _empty_store(self) -> Dict[str, Any]:
        return {"active": {}, "stations": {}}
