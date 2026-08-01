from __future__ import annotations

import re
from typing import Any, Dict

from voice.operational_log import log_event

from .request_semantics_bridge import RequestSemanticsDjGooAudioBridge


SESSION_PROFILES: dict[str, tuple[str, str]] = {
    "gaming": ("balanced", "high energy gaming music"),
    "competitive": ("bangers", "high energy focus music"),
    "lobby": ("balanced", "upbeat chill lobby music"),
    "party": ("bangers", "party hits"),
    "late-night": ("discovery", "late night chill music"),
    "latenight": ("discovery", "late night chill music"),
}


class ProfileDjGooAudioBridge(RequestSemanticsDjGooAudioBridge):
    """Translate game-session profiles into station-engine behavior."""

    def _session_profile(self, seed: str) -> tuple[str, str, str] | None:
        normalized = re.sub(r"\s+", " ", seed.strip())
        first, _separator, rest = normalized.partition(" ")
        key = first.lower()
        profile = SESSION_PROFILES.get(key)
        if profile is None:
            return None
        mode, default_seed = profile
        actual_seed = rest.strip() or default_seed
        return key, mode, actual_seed

    def _split_radio_mode(self, seed: str) -> tuple[str, str]:
        profile = self._session_profile(seed)
        if profile is not None:
            profile_name, mode, actual_seed = profile
            log_event(
                "radio.profile.selected",
                profile=profile_name,
                mode=mode,
                original_seed=seed,
                actual_seed=actual_seed,
            )
            return mode, actual_seed
        return super()._split_radio_mode(seed)

    def _station_reason(self, station: Dict[str, Any]) -> str:
        profile = self._session_profile(str(station.get("seed") or ""))
        if profile is not None:
            profile_name, _mode, _actual_seed = profile
            display = profile_name.replace("-", " ").title()
            if station.get("liked"):
                return f"{display} profile, steered by liked tracks"
            if station.get("more_like"):
                return f"{display} profile, steered by more-like-this"
            return f"{display} game-session profile"
        return super()._station_reason(station)
