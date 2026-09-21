from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


ROLES = {"host", "moderator", "member", "guest"}
VOTE_ACTIONS = {"skip", "more_like", "less_like", "ban"}
EXPLICIT_POLICIES = {"allow", "warn", "reject"}


DEFAULT_SETTINGS: dict[str, Any] = {
    "ranked_mode": False,
    "per_user_queue_limit": 3,
    "round_robin": True,
    "vote_thresholds": {"skip": 2, "more_like": 2, "less_like": 2, "ban": 2},
    "explicit_policy": "allow",
    "volume_normalization": True,
    "normalization_target": 90,
    "crossfade_enabled": False,
    "crossfade_seconds": 3,
    "preload_enabled": True,
    "media_keys_enabled": True,
}


@dataclass(frozen=True)
class VoteResult:
    execute: bool
    votes: int
    threshold: int
    duplicate: bool = False


class GamingSessionStore:
    """Durable identities and per-guild gameplay policy."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def settings(self, guild_id: int) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            guilds = data.setdefault("guilds", {})
            guild = guilds.get(str(int(guild_id)))
            if not isinstance(guild, dict) and int(guild_id) != 0:
                guild = guilds.get("0")
            if not isinstance(guild, dict):
                guild = self._guild(data, guild_id)
            return self._normalize_settings(guild.get("settings"))

    def update_settings(
        self,
        guild_id: int,
        updates: Mapping[str, Any],
        *,
        actor_role: str,
    ) -> dict[str, Any]:
        if actor_role != "host":
            raise PermissionError("Only the DjGoo host can change session policies")
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            settings = self._normalize_settings(guild.get("settings"))
            for key in DEFAULT_SETTINGS:
                if key not in updates:
                    continue
                settings[key] = updates[key]
            settings = self._normalize_settings(settings)
            guild["settings"] = settings
            self._write(data)
            return settings

    def create_profile(
        self,
        username: str,
        *,
        guild_id: int = 0,
        role: str = "member",
        device_id: str = "",
    ) -> dict[str, Any]:
        name = " ".join(str(username).split()).strip()
        if len(name) < 2 or len(name) > 32:
            raise ValueError("Username must contain 2 to 32 characters")
        normalized_role = role if role in ROLES else "member"
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            profiles = guild.setdefault("profiles", {})
            for profile in profiles.values():
                if str(profile.get("username") or "").casefold() == name.casefold():
                    if device_id and str(profile.get("device_id") or "") == device_id:
                        return dict(profile)
                    raise ValueError("That username is already in use")
            token = secrets.token_urlsafe(24)
            profile = {
                "id": secrets.token_hex(8),
                "token": token,
                "username": name,
                "role": normalized_role,
                "device_id": str(device_id)[:100],
                "created_at": time.time(),
                "last_seen": time.time(),
            }
            profiles[token] = profile
            self._write(data)
            return dict(profile)

    def profile(self, token: str, *, guild_id: int = 0) -> dict[str, Any] | None:
        if not token:
            return None
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            profile = guild.setdefault("profiles", {}).get(token)
            if not isinstance(profile, dict):
                return None
            profile["last_seen"] = time.time()
            self._write(data)
            return dict(profile)

    def profiles(self, guild_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            guild = self._guild(self._read(), guild_id)
            return [self._public_profile(item) for item in guild.get("profiles", {}).values() if isinstance(item, dict)]

    def set_role(self, guild_id: int, profile_id: str, role: str, *, actor_role: str) -> dict[str, Any]:
        if actor_role != "host":
            raise PermissionError("Only the DjGoo host can manage player permissions")
        if role not in ROLES:
            raise ValueError("Unknown player role")
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            for profile in guild.setdefault("profiles", {}).values():
                if isinstance(profile, dict) and str(profile.get("id")) == str(profile_id):
                    profile["role"] = role
                    self._write(data)
                    return self._public_profile(profile)
        raise ValueError("Player profile was not found")

    def can_direct_control(self, role: str) -> bool:
        return role in {"host", "moderator"}

    def queue_limit_reached(self, guild_id: int, requester_id: str, pending: Iterable[Mapping[str, Any]]) -> bool:
        if not requester_id:
            return False
        limit = int(self.settings(guild_id)["per_user_queue_limit"])
        return sum(str(item.get("requester_key") or item.get("requester_id") or "") == requester_id for item in pending) >= limit

    def fair_order(self, entries: list[Mapping[str, Any]]) -> list[str]:
        """Return stable entry IDs in requester round-robin order."""

        lanes: dict[str, list[str]] = {}
        order: list[str] = []
        for entry in entries:
            entry_id = str(entry.get("entry_id") or "")
            if not entry_id:
                continue
            requester = str(entry.get("requester_key") or entry.get("requester_id") or "system")
            if requester not in lanes:
                lanes[requester] = []
                order.append(requester)
            lanes[requester].append(entry_id)
        result: list[str] = []
        while any(lanes.values()):
            for requester in order:
                if lanes[requester]:
                    result.append(lanes[requester].pop(0))
        return result

    def cast_vote(
        self,
        guild_id: int,
        *,
        track_key: str,
        action: str,
        voter_key: str,
        role: str,
    ) -> VoteResult:
        if action not in VOTE_ACTIONS:
            raise ValueError("Unsupported vote action")
        if self.can_direct_control(role):
            return VoteResult(True, 1, 1)
        settings = self.settings(guild_id)
        threshold = int(settings["vote_thresholds"].get(action, 2))
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            votes = guild.setdefault("votes", {})
            vote_key = f"{track_key}:{action}"
            voters = votes.setdefault(vote_key, [])
            voter = str(voter_key or "anonymous")
            duplicate = voter in voters
            if not duplicate:
                voters.append(voter)
            count = len(voters)
            execute = count >= threshold
            if execute:
                votes.pop(vote_key, None)
            self._write(data)
            return VoteResult(execute, count, threshold, duplicate)

    def clear_track_votes(self, guild_id: int, track_key: str) -> None:
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            votes = guild.setdefault("votes", {})
            for key in list(votes):
                if key.startswith(f"{track_key}:"):
                    votes.pop(key, None)
            self._write(data)

    def record_undo(self, guild_id: int, action: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            guild["undo"] = {
                "action": str(action),
                "payload": dict(payload),
                "created_at": time.time(),
            }
            self._write(data)

    def pop_undo(self, guild_id: int, *, max_age_seconds: float = 120.0) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            guild = self._guild(data, guild_id)
            item = guild.pop("undo", None)
            self._write(data)
        if not isinstance(item, dict):
            return None
        if time.time() - float(item.get("created_at") or 0) > max_age_seconds:
            return None
        return item

    def public_state(self, guild_id: int = 0) -> dict[str, Any]:
        return {"settings": self.settings(guild_id), "profiles": self.profiles(guild_id)}

    @staticmethod
    def _public_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
        return {key: profile.get(key) for key in ("id", "username", "role", "created_at", "last_seen")}

    def _guild(self, data: dict[str, Any], guild_id: int) -> dict[str, Any]:
        return data.setdefault("guilds", {}).setdefault(
            str(int(guild_id)),
            {"settings": dict(DEFAULT_SETTINGS), "profiles": {}, "votes": {}},
        )

    @staticmethod
    def _normalize_settings(value: Any) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(value, Mapping):
            settings.update({key: value[key] for key in DEFAULT_SETTINGS if key in value})
        settings["ranked_mode"] = bool(settings["ranked_mode"])
        settings["round_robin"] = bool(settings["round_robin"])
        settings["per_user_queue_limit"] = max(1, min(25, int(settings["per_user_queue_limit"])))
        thresholds = settings.get("vote_thresholds") if isinstance(settings.get("vote_thresholds"), Mapping) else {}
        settings["vote_thresholds"] = {action: max(1, min(20, int(thresholds.get(action, 2)))) for action in VOTE_ACTIONS}
        policy = str(settings["explicit_policy"]).lower()
        settings["explicit_policy"] = policy if policy in EXPLICIT_POLICIES else "allow"
        settings["volume_normalization"] = bool(settings["volume_normalization"])
        settings["normalization_target"] = max(20, min(150, int(settings["normalization_target"])))
        settings["crossfade_enabled"] = bool(settings["crossfade_enabled"])
        settings["crossfade_seconds"] = max(1, min(10, int(settings["crossfade_seconds"])))
        settings["preload_enabled"] = bool(settings["preload_enabled"])
        settings["media_keys_enabled"] = bool(settings["media_keys_enabled"])
        return settings

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": 1, "guilds": {}}
        return data if isinstance(data, dict) else {"schema": 1, "guilds": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
