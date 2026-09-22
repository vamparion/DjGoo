from __future__ import annotations

import json
import random
import re
import sqlite3
import copy
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from voice.djgoo_stations import display_station_name, normalize_station_seed, station_id, track_key


RECENT_LIMIT = 50
PLAYED_LIMIT = 2_000
FEEDBACK_BUCKETS = {"liked", "banned", "more_like", "less_like", "skipped"}
RADIO_MODES = {"bangers", "balanced", "discovery", "throwbacks"}
STATION_DEFAULTS = {"familiar_percent": 55, "discovery_percent": 20, "artist_spacing": 4, "song_spacing": 50, "seed_type": "auto", "seed_examples": [], "snapshots": [], "feedback_history": []}


class SqliteDjGooStations:
    """Drop-in DjGooStations replacement with atomic cross-task writes."""

    def __init__(self, path: Path, *, legacy_json_path: Path | None = None) -> None:
        self.path = path
        self.legacy_json_path = legacy_json_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._migrate_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS stations (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active_stations (
                    guild_id INTEGER PRIMARY KEY,
                    station_id TEXT NOT NULL,
                    FOREIGN KEY(station_id) REFERENCES stations(id)
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate_legacy_json(self) -> None:
        legacy = self.legacy_json_path
        if legacy is None or not legacy.exists():
            return
        with self._connect() as connection:
            migrated = connection.execute(
                "SELECT value FROM metadata WHERE key = 'legacy_json_migrated'"
            ).fetchone()
            existing = connection.execute("SELECT COUNT(*) AS count FROM stations").fetchone()["count"]
        if migrated or existing:
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        stations = data.get("stations", {}) if isinstance(data, dict) else {}
        active = data.get("active", {}) if isinstance(data, dict) else {}
        if not isinstance(stations, dict):
            return
        now = self._now()
        with self._transaction() as connection:
            for identifier, station in stations.items():
                if not isinstance(station, dict):
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO stations(id, payload, updated_at) VALUES (?, ?, ?)",
                    (str(identifier), json.dumps(station, ensure_ascii=False), now),
                )
            if isinstance(active, dict):
                for guild_id, identifier in active.items():
                    try:
                        numeric_guild_id = int(guild_id)
                    except (TypeError, ValueError):
                        continue
                    if str(identifier) in stations:
                        connection.execute(
                            "INSERT OR REPLACE INTO active_stations(guild_id, station_id) VALUES (?, ?)",
                            (numeric_guild_id, str(identifier)),
                        )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('legacy_json_migrated', ?)",
                (now,),
            )

    def _load_station(self, connection: sqlite3.Connection, identifier: str) -> Optional[Dict[str, Any]]:
        row = connection.execute("SELECT payload FROM stations WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            return None
        try:
            station = json.loads(row["payload"])
        except json.JSONDecodeError:
            return None
        if not isinstance(station, dict):
            return None
        for key, value in STATION_DEFAULTS.items():
            station.setdefault(key, copy.deepcopy(value))
        return station

    def _save_station(self, connection: sqlite3.Connection, station: Dict[str, Any]) -> None:
        station["updated_at"] = self._now()
        connection.execute(
            "INSERT OR REPLACE INTO stations(id, payload, updated_at) VALUES (?, ?, ?)",
            (station["id"], json.dumps(station, ensure_ascii=False), station["updated_at"]),
        )

    def get_or_create(self, seed: str) -> Dict[str, Any]:
        identifier = station_id(seed)
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                now = self._now()
                station = {
                    "id": identifier,
                    "name": display_station_name(seed),
                    "seed": self._clean_seed(seed),
                    "mode": "balanced",
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
                self._save_station(connection, station)
            return station

    def set_mode(self, seed: str, mode: str) -> Dict[str, Any]:
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in RADIO_MODES:
            raise ValueError(f"Unknown radio mode: {mode}")
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                raise RuntimeError(f"Station disappeared during update: {identifier}")
            station["mode"] = normalized_mode
            self._save_station(connection, station)
            return station

    def get_station(self, seed: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            return self._load_station(connection, station_id(seed))

    def set_active(self, guild_id: int, seed: str) -> Dict[str, Any]:
        station = self.get_or_create(seed)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO active_stations(guild_id, station_id) VALUES (?, ?)",
                (int(guild_id), station["id"]),
            )
        return station

    def get_active(self, guild_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT station_id FROM active_stations WHERE guild_id = ?",
                (int(guild_id),),
            ).fetchone()
            return self._load_station(connection, row["station_id"]) if row else None

    def active_guild_ids(self) -> List[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT guild_id FROM active_stations ORDER BY guild_id").fetchall()
        return [int(row["guild_id"]) for row in rows]

    def clear_active(self, guild_id: int) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM active_stations WHERE guild_id = ?", (int(guild_id),))

    def clear_all_active(self) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM active_stations")

    def add_feedback(self, seed: str, feedback_type: str, track: Dict[str, Any]) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                raise RuntimeError(f"Station disappeared during update: {identifier}")
            tracks = station.setdefault(feedback_type, [])
            cleaned = self._clean_track(track)
            existing_keys = {track_key(item) for item in tracks if isinstance(item, dict)}
            if track_key(cleaned) not in existing_keys:
                tracks.append(cleaned)
                station.setdefault("feedback_history", []).append({"id": uuid.uuid4().hex, "action": feedback_type, "track": cleaned, "created_at": self._now()})
                del station["feedback_history"][:-500]
                del tracks[:-PLAYED_LIMIT]
                self._save_station(connection, station)
            return station

    def remove_feedback(self, seed: str, feedback_type: str, track: Dict[str, Any]) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        identifier = self.get_or_create(seed)["id"]
        key = track_key(track)
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                raise RuntimeError(f"Station disappeared during update: {identifier}")
            station[feedback_type] = [
                item for item in station.get(feedback_type, [])
                if not isinstance(item, dict) or track_key(item) != key
            ]
            self._save_station(connection, station)
            return station

    def undo_feedback(self, seed: str, feedback_type: str) -> Dict[str, Any]:
        if feedback_type not in FEEDBACK_BUCKETS:
            raise ValueError(f"Unknown feedback bucket: {feedback_type}")
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            history = station.setdefault("feedback_history", [])
            match = next((item for item in reversed(history) if item.get("action") == feedback_type), None)
            if match is None:
                raise ValueError(f"No recent {feedback_type.replace('_', ' ')} feedback to undo")
            key = track_key(match.get("track") or {})
            station[feedback_type] = [item for item in station.get(feedback_type, []) if track_key(item) != key]
            history.remove(match)
            self._save_station(connection, station)
            return station

    def update_settings(self, seed: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            for key in ("familiar_percent", "discovery_percent", "artist_spacing", "song_spacing"):
                if key in updates:
                    station[key] = max(0, min(100 if "percent" in key else 200, int(updates[key])))
            for key in ("seed_type", "description"):
                if key in updates:
                    station[key] = str(updates[key]).strip()[:500]
            if "seed_examples" in updates and isinstance(updates["seed_examples"], list):
                station["seed_examples"] = [str(value).strip()[:200] for value in updates["seed_examples"] if str(value).strip()][:20]
            self._save_station(connection, station)
            return station

    def set_selection_reason(self, seed: str, reason: str, *, drift_score: int = 0) -> None:
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            station["last_selection_reason"] = str(reason).strip()[:300]
            station["last_drift_score"] = max(0, min(100, int(drift_score)))
            self._save_station(connection, station)

    def create_snapshot(self, seed: str, name: str = "") -> Dict[str, Any]:
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            snapshot = {"id": uuid.uuid4().hex, "name": str(name).strip()[:80] or f"Snapshot {len(station.get('snapshots', [])) + 1}", "created_at": self._now(), "state": {key: copy.deepcopy(value) for key, value in station.items() if key not in {"snapshots", "played", "recent", "last_track"}}}
            station.setdefault("snapshots", []).append(snapshot)
            del station["snapshots"][:-20]
            self._save_station(connection, station)
            return snapshot

    def restore_snapshot(self, seed: str, snapshot_id: str) -> Dict[str, Any]:
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            snapshot = next((item for item in station.get("snapshots", []) if str(item.get("id")) == str(snapshot_id)), None)
            if not isinstance(snapshot, dict):
                raise ValueError("Station snapshot was not found")
            preserved = {key: station.get(key) for key in ("played", "recent", "last_track", "snapshots")}
            station.update(copy.deepcopy(snapshot.get("state") or {}))
            station.update(preserved)
            self._save_station(connection, station)
            return station

    def clone(self, seed: str, new_seed: str) -> Dict[str, Any]:
        source = self.get_station(seed)
        identifier = station_id(new_seed)
        if source is None:
            raise ValueError(f"Station not found: {seed}")
        with self._transaction() as connection:
            if self._load_station(connection, identifier):
                raise ValueError(f"Station already exists: {new_seed}")
            clone = copy.deepcopy(source)
            clone.update({"id": identifier, "name": display_station_name(new_seed), "seed": self._clean_seed(new_seed), "created_at": self._now(), "played": [], "recent": [], "last_track": None, "snapshots": []})
            self._save_station(connection, clone)
            return clone

    def merge(self, seeds: List[str], new_seed: str) -> Dict[str, Any]:
        sources = [self.get_station(seed) for seed in seeds]
        sources = [item for item in sources if item]
        if len(sources) < 2:
            raise ValueError("Choose at least two existing stations to merge")
        target = self.get_or_create(new_seed)
        with self._transaction() as connection:
            merged = self._load_station(connection, target["id"])
            for bucket in FEEDBACK_BUCKETS:
                merged[bucket] = list({track_key(item): item for source in sources for item in source.get(bucket, []) if isinstance(item, dict)}.values())
            merged["seed_examples"] = list(dict.fromkeys([source.get("seed", "") for source in sources] + [example for source in sources for example in source.get("seed_examples", [])]))[:20]
            merged["played"], merged["recent"], merged["last_track"] = [], [], None
            self._save_station(connection, merged)
            return merged

    def all_stations(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id FROM stations ORDER BY updated_at DESC").fetchall()
            return [station for row in rows if (station := self._load_station(connection, row["id"])) is not None]

    def mark_played(self, seed: str, track: Dict[str, Any]) -> Dict[str, Any]:
        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                raise RuntimeError(f"Station disappeared during update: {identifier}")
            cleaned = self._clean_track(track)
            played = station.setdefault("played", [])
            recent = station.setdefault("recent", [])
            played.append(cleaned)
            recent.append(cleaned)
            del played[:-PLAYED_LIMIT]
            del recent[:-RECENT_LIMIT]
            station["last_track"] = cleaned
            self._save_station(connection, station)
            return station

    def set_seed_track(self, seed: str, track: Dict[str, Any]) -> Dict[str, Any]:
        """Remember the exact seed without counting it as already played."""

        identifier = self.get_or_create(seed)["id"]
        with self._transaction() as connection:
            station = self._load_station(connection, identifier)
            if station is None:
                raise RuntimeError(f"Station disappeared during update: {identifier}")
            station["seed_track"] = self._clean_track(track)
            self._save_station(connection, station)
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
        return random.Random(rng_seed).choice(available)

    def _clean_track(self, track: Dict[str, Any]) -> Dict[str, str]:
        return {
            "title": str(track.get("title", "")).strip(),
            "artist": str(track.get("artist", "")).strip(),
            "uri": str(track.get("uri", "")).strip(),
            "duration_seconds": str(track.get("duration_seconds", "")).strip(),
        }

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _clean_seed(self, seed: str) -> str:
        return re.sub(r"\s+", " ", seed.strip())
