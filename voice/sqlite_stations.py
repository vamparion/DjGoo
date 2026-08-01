from __future__ import annotations

import json
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from voice.djgoo_stations import display_station_name, normalize_station_seed, station_id, track_key


RECENT_LIMIT = 50
PLAYED_LIMIT = 2_000
FEEDBACK_BUCKETS = {"liked", "banned", "more_like", "less_like", "skipped"}


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
        return station if isinstance(station, dict) else None

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
