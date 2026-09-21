from __future__ import annotations

import asyncio
import inspect
import math
import random
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.media_policy import (
    CanonicalTrack,
    candidates_from_ytmusic,
    pick_radio_candidate,
    ranked_search_candidates,
    score_search_candidate,
    search_match_is_confident,
    title_is_rejected,
    track_identity,
)
from voice.operational_log import log_event
from voice.sqlite_stations import SqliteDjGooStations
from voice.pending_choices import PendingChoiceStore

from .audio_bridge import DjGooAudioBridge


RADIO_MODES = {"bangers", "balanced", "discovery", "throwbacks"}
_RANKED_CHOICES: ContextVar[tuple[Dict[str, Any], ...]] = ContextVar(
    "djgoo_ranked_choices",
    default=(),
)


class EnhancedDjGooAudioBridge(DjGooAudioBridge):
    """Keep Red Audio as playback authority while improving selection and controls."""

    def __init__(self, *, bot, project_root: Path, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self.stations = SqliteDjGooStations(
            project_root / "data" / "djgoo-stations.sqlite3",
            legacy_json_path=project_root / "data" / "djgoo-stations.json",
        )
        self.pending_choices = PendingChoiceStore(
            project_root / "data" / "djgoo-pending-choice.json"
        )
        if not self._should_resume_playback():
            self.stations.clear_all_active()

    async def handle(self, item: Dict[str, Any]) -> str:
        if str(item.get("type") or "") == "followup":
            action = str(item.get("action") or "").lower()
            if action in {"neither", "cancel", "expired"}:
                self.pending_choices.clear()
                return "Song choices cleared"
            index = item.get("index")
            if action == "select" and index is not None:
                selected = self.pending_choices.choose(int(index))
                if selected is None:
                    return "Song choice expired"
                return await super().handle(
                    {
                        **item,
                        "type": "command",
                        "intent": "play",
                        "query": str(selected.get("uri") or ""),
                    }
                )
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
            if await self._skip_playback(audio, ctx):
                return "Removed current track"
            return "Remove current failed: player did not advance"

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
        else:
            requested_title = query
            requested_artists: tuple[str, ...] = ()
            title_artist = re.match(
                r"^\s*(?P<title>.+?)\s+by\s+(?P<artist>.+?)\s*$",
                query,
                flags=re.IGNORECASE,
            )
            if title_artist is not None:
                requested_title = title_artist.group("title")
                requested_artists = (title_artist.group("artist"),)
            canonical = CanonicalTrack(
                title=requested_title,
                artists=requested_artists,
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
        ranked_choices = list(_RANKED_CHOICES.get())
        if ranked_choices:
            ctx = self._context()
            guild_id = int(getattr(getattr(ctx, "guild", None), "id", 0) or 0)
            self.pending_choices.set(
                query=query,
                options=ranked_choices,
                guild_id=guild_id,
            )
            lines = ["DjGoo needs a choice:"]
            lines.extend(
                f"{index}. {choice.get('artist', '')} - {choice.get('title', '')}".strip(" -")
                for index, choice in enumerate(ranked_choices, start=1)
            )
            lines.append("Say `Number 1`, `Number 2`, `Number 3`, `Number 4`, or `Neither` within 15 seconds.")
            await self._notice("\n".join(lines))
            log_event(
                "play.resolve.choice_required",
                query=query,
                guild_id=guild_id,
                choices=ranked_choices,
            )
            return []
        if nuclear_track is not None:
            return [nuclear_track.redbot_query()]
        return await super()._resolve_play_queries(query, source=source)

    def _ranked_ytmusic_song(self, query: str, canonical: CanonicalTrack | None) -> Optional[str]:
        _RANKED_CHOICES.set(())
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        try:
            items = self._ytmusic.search(query, filter="songs", limit=10)
        except Exception as exc:
            log_event("ytmusic.ranked_search.failed", query=query, error=type(exc).__name__, detail=str(exc))
            return None
        candidates = candidates_from_ytmusic(items or [])
        ranked = ranked_search_candidates(candidates, canonical)
        selected = ranked[0][1] if ranked else None
        confident = search_match_is_confident(ranked, canonical)
        _RANKED_CHOICES.set(tuple(
            {
                "title": candidate.title,
                "artist": ", ".join(candidate.artists),
                "uri": candidate.uri,
                "duration_seconds": candidate.duration_seconds,
                "score": round(score, 2),
            }
            for score, candidate in ranked[:4]
        ) if selected is not None and not confident else ())
        log_event(
            "ytmusic.ranked_search.result",
            query=query,
            candidate_count=len(candidates),
            selected=selected.display_title if selected else None,
            selected_duration=selected.duration_seconds if selected else 0,
            canonical_duration=canonical.duration_seconds if canonical else 0,
            confident=confident,
        )
        return selected.uri if selected and confident else None

    async def search_candidates(self, query: str, *, limit: int = 4) -> List[Dict[str, Any]]:
        cleaned_query = re.sub(r"\s+", " ", str(query).strip())
        if not cleaned_query:
            return []
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        try:
            items = await asyncio.to_thread(
                self._ytmusic.search,
                cleaned_query,
                filter="songs",
                limit=max(10, int(limit) * 3),
            )
        except Exception as exc:
            log_event(
                "ytmusic.mini_search.failed",
                query=cleaned_query,
                error=type(exc).__name__,
                detail=str(exc),
            )
            return []
        candidates = candidates_from_ytmusic(items or [])
        ranked = sorted(
            (
                (score_search_candidate(candidate, None), candidate)
                for candidate in candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        results: List[Dict[str, Any]] = []
        for score, candidate in ranked:
            if not math.isfinite(score):
                continue
            video_id = self._youtube_video_id(candidate.uri)
            results.append(
                {
                    "id": video_id or candidate.uri,
                    "title": candidate.title,
                    "artist": ", ".join(candidate.artists),
                    "duration_seconds": candidate.duration_seconds,
                    "uri": candidate.uri,
                    "source": "YouTube Music",
                    "artwork_url": (
                        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
                        if video_id
                        else ""
                    ),
                }
            )
            if len(results) >= max(1, int(limit)):
                break
        log_event(
            "ytmusic.mini_search.result",
            query=cleaned_query,
            candidate_count=len(candidates),
            returned_count=len(results),
        )
        return results

    def _repair_voice_play_query(self, query: str) -> str:
        # Phrase corrections now come from data/voice-corrections.json.
        return re.sub(r"\s+", " ", query).strip()

    def _track_data(self, track) -> Dict[str, str]:
        data = super()._track_data(track)
        info = getattr(track, "info", {}) or {}
        artist = getattr(track, "author", "") or info.get("author", "") or info.get("artist", "")
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

    def _split_radio_mode(self, seed: str) -> tuple[str, str]:
        normalized = re.sub(r"\s+", " ", seed.strip())
        first, separator, rest = normalized.partition(" ")
        mode = first.lower()
        if mode not in RADIO_MODES:
            return "balanced", normalized
        if rest:
            return mode, rest
        defaults = {
            "bangers": "popular hits",
            "balanced": "popular music",
            "discovery": "new music recommendations",
            "throwbacks": "80s 90s 2000s hits",
        }
        return mode, defaults[mode]

    def _radio_seed_search_query(self, seed: str) -> str:
        mode, actual_seed = self._split_radio_mode(seed)
        query = super()._radio_seed_search_query(actual_seed)
        log_event("radio.mode.seed", mode=mode, original_seed=seed, search_query=query)
        return query

    def _pick_recommended_track(self, station: Dict[str, Any], tracks) -> Optional[Dict[str, str]]:
        mode = str(station.get("mode") or "").strip().lower()
        if mode not in RADIO_MODES:
            mode, _actual_seed = self._split_radio_mode(str(station.get("seed", "")))
        source_tracks = [
            track
            for track in (tracks or [])
            if isinstance(track, dict)
            and not self._is_bad_radio_variant_title(str(track.get("title") or ""))
        ]
        if mode == "throwbacks":
            dated = []
            for track in source_tracks:
                try:
                    year = int(track.get("year") or 0)
                except (TypeError, ValueError):
                    year = 0
                if not year or year <= 2012:
                    dated.append(track)
            if dated:
                source_tracks = dated

        candidates = candidates_from_ytmusic(source_tracks)
        if mode == "bangers":
            # Watch-playlist order is YouTube Music's strongest available relevance signal.
            candidates = sorted(candidates, key=lambda item: item.result_index)[:8]
        elif mode == "discovery" and len(candidates) > 5:
            # Avoid always replaying the safest first recommendation in discovery mode.
            candidates = candidates[2:]

        selected = pick_radio_candidate(candidates, station)
        if selected is None:
            log_event(
                "radio.recommendation.ranked_empty",
                station=station.get("name"),
                mode=mode,
                count=len(candidates),
            )
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
            mode=mode,
            candidate_count=len(candidates),
            selected=result,
        )
        return result

    def _station_reason(self, station: Dict[str, Any]) -> str:
        mode = str(station.get("mode") or "").strip().lower()
        if mode not in RADIO_MODES:
            mode, _actual_seed = self._split_radio_mode(str(station.get("seed", "")))
        if station.get("liked"):
            return f"{mode.title()} mode, steered by liked tracks"
        if station.get("more_like"):
            return f"{mode.title()} mode, steered by more-like-this"
        return f"{mode.title()} mode recommendation"
