from __future__ import annotations

import asyncio
import contextlib
import inspect
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.media_policy import (
    CanonicalTrack,
    MediaCandidate,
    candidates_from_ytmusic,
    pick_best_search_candidate,
    pick_radio_candidate,
    title_is_rejected,
    track_identity,
)
from voice.operational_log import log_event
from voice.sqlite_stations import SqliteDjGooStations

from .audio_bridge import DjGooAudioBridge


class EnhancedDjGooAudioBridge(DjGooAudioBridge):
    """Keep Red Audio as playback authority while improving selection and controls."""

    def __init__(self, *, bot, project_root: Path, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self.stations = SqliteDjGooStations(
            project_root / "data" / "djgoo-stations.sqlite3",
            legacy_json_path=project_root / "data" / "djgoo-stations.json",
        )
        if not self._should_resume_playback():
            self.stations.clear_all_active()

    async def handle(self, item: Dict[str, Any]) -> str:
        intent = str(item.get("intent", ""))
        if intent in {
            "seek",
            "remove_queue",
            "shuffle_queue",
            "repeat",
            "autoplay",
            "favorite_current",
            "undo_station_ban",
            "remove_current",
        }:
            return await self._handle_extended_intent(item)
        return await super().handle(item)

    async def _handle_extended_intent(self, item: Dict[str, Any]) -> str:
        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            await self._notice("Join a voice channel and make sure Audio is loaded.")
            return "No audio context"
        intent = str(item.get("intent", ""))

        if intent == "seek":
            seconds = max(0, int(item.get("value") or 0))
            try:
                player = lavalink.get_player(ctx.guild.id)
            except (NodeNotFound, PlayerNotFound):
                await self._notice("Nothing is playing.")
                return "Nothing playing"
            result = player.seek(seconds * 1000)
            if inspect.isawaitable(result):
                await result
            await self._notice(f"Seeked to {seconds // 60}:{seconds % 60:02d}.")
            return f"Seeked {seconds} seconds"

        if intent == "remove_queue":
            position = int(item.get("value") or 0)
            try:
                player = lavalink.get_player(ctx.guild.id)
            except (NodeNotFound, PlayerNotFound):
                await self._notice("The queue is empty.")
                return "Queue empty"
            queue = list(player.queue)
            if position < 1 or position > len(queue):
                await self._notice(f"Choose a queue number from 1 to {len(queue)}.")
                return "Invalid queue position"
            removed = queue.pop(position - 1)
            player.queue.clear()
            player.queue.extend(queue)
            await self._notice(f"Removed `{getattr(removed, 'title', 'that track')}` from the queue.")
            self._persist_player_state(ctx.guild.id, reason="queue_remove")
            return f"Removed queue item {position}"

        if intent == "shuffle_queue":
            try:
                player = lavalink.get_player(ctx.guild.id)
            except (NodeNotFound, PlayerNotFound):
                await self._notice("The queue is empty.")
                return "Queue empty"
            queue = list(player.queue)
            random.shuffle(queue)
            player.queue.clear()
            player.queue.extend(queue)
            self._persist_player_state(ctx.guild.id, reason="queue_shuffle")
            await self._notice(f"Shuffled {len(queue)} queued track(s).")
            return "Queue shuffled"

        if intent in {"repeat", "autoplay"}:
            command_name = "command_repeat" if intent == "repeat" else "command_autoplay"
            command = getattr(audio, command_name, None)
            if command is None:
                await self._notice(f"This Red Audio version does not expose `{intent}` yet.")
                return f"{intent} unavailable"
            await self._invoke(command, ctx)
            return f"Toggled {intent}"

        if intent == "favorite_current":
            return await self._save_track(ctx, "favorites", last=False)

        if intent == "undo_station_ban":
            station = self.stations.get_active(ctx.guild.id)
            if station is None or not station.get("banned"):
                await self._notice("There is no recent station ban to undo.")
                return "No ban to undo"
            track = station["banned"][-1]
            self.stations.remove_feedback(station["seed"], "banned", track)
            await self._notice(f"Allowed `{track.get('title', 'that track')}` again.")
            return "Station ban undone"

        if intent == "remove_current":
            await self._invoke_silently(audio.command_skip, ctx)
            return "Removed current track"

        return await super().handle(item)

    async def _resolve_play_queries(self, query: str, *, source: str = "") -> List[str]:
        original_query = query
        query = self._repair_voice_play_query(query) if source == "voice" else query.strip()
        if self._is_youtube_url(query):
            return await super()._resolve_play_queries(query, source=source)

        nuclear_track = await asyncio.to_thread(self.nuclear.resolve_track, query)
        canonical = None
        if nuclear_track is not None:
            canonical = CanonicalTrack(
                title=nuclear_track.title,
                artists=tuple(nuclear_track.artists),
                duration_seconds=nuclear_track.duration_seconds,
                isrc=nuclear_track.isrc,
            )
        resolved = await asyncio.to_thread(self._ranked_ytmusic_song, query, canonical)
        if resolved:
            log_event(
                "play.resolve.ranked",
                original_query=original_query,
                query=query,
                resolved_query=resolved,
                canonical_title=canonical.title if canonical else None,
                canonical_duration=canonical.duration_seconds if canonical else 0,
            )
            return [resolved]
        if nuclear_track is not None:
            return [nuclear_track.redbot_query()]
        return await super()._resolve_play_queries(query, source=source)

    def _ranked_ytmusic_song(self, query: str, canonical: CanonicalTrack | None) -> Optional[str]:
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        try:
            items = self._ytmusic.search(query, filter="songs", limit=10)
        except Exception as exc:
            log_event("ytmusic.ranked_search.failed", query=query, error=type(exc).__name__, detail=str(exc))
            return None
        candidates = candidates_from_ytmusic(items or [])
        selected = pick_best_search_candidate(candidates, canonical)
        log_event(
            "ytmusic.ranked_search.result",
            query=query,
            candidate_count=len(candidates),
            selected=selected.display_title if selected else None,
            selected_duration=selected.duration_seconds if selected else 0,
            canonical_duration=canonical.duration_seconds if canonical else 0,
        )
        return selected.uri if selected else None

    def _repair_voice_play_query(self, query: str) -> str:
        # Phrase corrections now come from data/voice-corrections.json.
        return re.sub(r"\s+", " ", query).strip()

    def _track_data(self, track) -> Dict[str, str]:
        data = super()._track_data(track)
        info = getattr(track, "info", {}) or {}
        artist = (
            getattr(track, "author", "")
            or info.get("author", "")
            or info.get("artist", "")
        )
        if artist:
            data["artist"] = str(artist).strip()
        return data

    async def _mark_station_skip(self, ctx) -> None:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            return
        track = self._selected_track(ctx.guild.id, last=False)
        if track is None:
            return
        data = self._track_data(track)
        self.stations.add_feedback(station["seed"], "skipped", data)
        self.stations.mark_played(station["seed"], data)
        log_event("radio.skip.negative_feedback", guild_id=ctx.guild.id, station=station["name"], track=data)

    def _station_rejects_track(self, station: Dict[str, Any], data: Dict[str, str]) -> bool:
        if self._should_reject_playing_track(data):
            return True
        identity = track_identity(data)
        blocked = [
            track
            for bucket in ("banned", "recent")
            for track in station.get(bucket, [])
            if isinstance(track, dict)
        ]
        return identity in {track_identity(track) for track in blocked}

    def _is_bad_radio_title(self, title: str) -> bool:
        return title_is_rejected(title)

    def _pick_recommended_track(self, station: Dict[str, Any], tracks) -> Optional[Dict[str, str]]:
        candidates = candidates_from_ytmusic(tracks or [])
        selected = pick_radio_candidate(candidates, station)
        if selected is None:
            log_event("radio.recommendation.ranked_empty", station=station.get("name"), count=len(candidates))
            return None
        result = {
            "title": selected.display_title,
            "artist": ", ".join(selected.artists),
            "uri": selected.uri,
            "duration_seconds": str(selected.duration_seconds or 0),
        }
        log_event(
            "radio.recommendation.ranked",
            station=station.get("name"),
            candidate_count=len(candidates),
            selected=result,
        )
        return result
