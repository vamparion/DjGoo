from __future__ import annotations

import asyncio
import random
from collections import Counter
from typing import Any, Dict

import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.operational_log import log_event

from .enhanced_audio_bridge import EnhancedDjGooAudioBridge


class GameFirstDjGooAudioBridge(EnhancedDjGooAudioBridge):
    """Add a request lane that returns cleanly to the active radio station.

    Red Audio remains the only queue authority. During radio playback, a normal
    DjGoo ``play`` request is delegated to Red's supported ``bumpplay`` command,
    placing one selected track at the front of the queue without disabling the
    station. Station-generated tracks continue behind it.
    """

    def __init__(self, *, bot, project_root, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self._radio_request_counts: dict[int, Counter[str]] = {}
        self._active_radio_request: dict[int, str] = {}
        self._station_top_up_locks: dict[int, asyncio.Lock] = {}

    async def handle(self, item: Dict[str, Any]) -> str:
        if str(item.get("intent", "")) != "play":
            return await super().handle(item)

        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            return await super().handle(item)

        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            return await super().handle(item)

        query = str(item.get("query", "")).strip()
        if not query:
            return await super().handle(item)

        resolved_queries = await self._resolve_play_queries(
            query,
            source=str(item.get("source", "")),
        )
        if not resolved_queries:
            await self._notice("I could not find a clean playable version of that request.")
            return "No clean radio request"

        # A radio request is deliberately one track. Playlist and album commands
        # retain their explicit queue behavior instead of silently flooding this lane.
        resolved_query = resolved_queries[0]
        log_event(
            "radio.request.received",
            guild_id=ctx.guild.id,
            station=station.get("name"),
            original_query=query,
            resolved_query=resolved_query,
            source=item.get("source"),
        )
        return await self._queue_radio_request(
            audio,
            ctx,
            resolved_query,
            station_name=str(station.get("name") or "radio"),
        )

    async def _queue_radio_request(
        self,
        audio: Any,
        ctx: Any,
        query: str,
        *,
        station_name: str,
    ) -> str:
        if not self._lavalink_node_ready(ctx.guild.id):
            await self._notice("DjGoo is warming up the music engine before adding that request.")
        if not await self._wait_for_lavalink_node(ctx.guild.id):
            await self._notice("The request was not queued because the music engine is unavailable.")
            return "Radio request startup failed"

        try:
            player_before = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            player_before = None
        prior_queue_ids = {
            id(track) for track in list(getattr(player_before, "queue", []) or [])
        }
        prior_track_ids = set(prior_queue_ids)
        prior_current = getattr(player_before, "current", None)
        if prior_current is not None:
            prior_track_ids.add(id(prior_current))

        bumpplay = getattr(audio, "command_bumpplay", None)
        if bumpplay is not None:
            await self._invoke_silently(
                bumpplay,
                ctx,
                play_now=False,
                query=query,
            )
        else:
            # Compatibility fallback for a future Red version that removes bumpplay.
            # Use command_play, then move only the newly appended objects to the front.
            await self._invoke_silently(audio.command_play, ctx, query=query)
            self._promote_new_queue_entries(ctx.guild.id, prior_queue_ids)

        requested_track = await self._requested_track_after_enqueue(
            ctx.guild.id,
            prior_track_ids=prior_track_ids,
        )
        if requested_track is None:
            await self._notice(
                "Red Audio did not add that request, so the radio queue was left unchanged."
            )
            log_event(
                "radio.request.enqueue_failed",
                guild_id=ctx.guild.id,
                station=station_name,
                query=query,
            )
            return "Radio request enqueue failed"

        self._remember_radio_request(ctx.guild.id, requested_track)
        track_data = self._track_data(requested_track)
        display = track_data.get("title") or query
        self._persist_player_state(ctx.guild.id, reason="radio_request_enqueued")
        await self._notice(
            f"Queued `{display}` next. `{station_name}` will resume automatically afterward."
        )
        log_event(
            "radio.request.queued_next",
            guild_id=ctx.guild.id,
            station=station_name,
            query=query,
            track=self._track_data(requested_track),
        )
        return f"Queued request next: {display}"

    def _promote_new_queue_entries(self, guild_id: int, prior_queue_ids: set[int]) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        queue = list(player.queue)
        added = [track for track in queue if id(track) not in prior_queue_ids]
        if not added:
            return
        retained = [track for track in queue if id(track) in prior_queue_ids]
        player.queue.clear()
        player.queue.extend([*added, *retained])

    def _new_track_from_player(self, player: Any, prior_track_ids: set[int]):
        current = getattr(player, "current", None)
        if current is not None and id(current) not in prior_track_ids:
            return current
        for track in list(getattr(player, "queue", []) or []):
            if id(track) not in prior_track_ids:
                return track
        return None

    async def _requested_track_after_enqueue(
        self,
        guild_id: int,
        *,
        prior_track_ids: set[int],
        timeout: float = 5.0,
    ):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                player = lavalink.get_player(guild_id)
            except (NodeNotFound, PlayerNotFound):
                player = None
            if player is not None:
                requested = self._new_track_from_player(player, prior_track_ids)
                if requested is not None:
                    return requested
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.1)

    def _request_counter(self, guild_id: int) -> Counter[str]:
        return self._radio_request_counts.setdefault(int(guild_id), Counter())

    def _remember_radio_request(self, guild_id: int, track: Any) -> None:
        key = self._track_key(track)
        if key:
            self._request_counter(guild_id)[key] += 1

    def _consume_radio_request(self, guild_id: int, track: Any) -> bool:
        key = self._track_key(track)
        extras = getattr(track, "extras", {}) or {}
        bumped = False
        try:
            bumped = bool(extras.get("bumped"))
        except AttributeError:
            bumped = False

        counter = self._request_counter(guild_id)
        remembered = bool(key and counter.get(key, 0) > 0)
        if remembered:
            counter[key] -= 1
            if counter[key] <= 0:
                del counter[key]
        if not counter:
            self._radio_request_counts.pop(int(guild_id), None)
        return bumped or remembered

    async def handle_station_track_start(self, guild: Any, track: Any) -> None:
        guild_id = int(guild.id)
        station = self.stations.get_active(guild_id)
        if station is not None and self._consume_radio_request(guild_id, track):
            key = self._track_key(track)
            self._active_radio_request[guild_id] = key
            data = self._track_data(track)
            log_event(
                "radio.request.started",
                guild_id=guild_id,
                station=station.get("name"),
                track=data,
            )
            await self._send_payload(
                {
                    "username": "DjGoo",
                    "embeds": [
                        {
                            "title": (data.get("title") or "Requested track")[:256],
                            "description": (
                                f"Requested song playing now. **{station.get('name', 'Radio')}** "
                                "continues after this track."
                            ),
                            "color": 0xF2994A,
                        }
                    ],
                }
            )
            await self._top_up_station_queue(guild_id)
            return

        self._active_radio_request.pop(guild_id, None)
        await super().handle_station_track_start(guild, track)

    async def _mark_station_skip(self, ctx: Any) -> None:
        guild_id = int(ctx.guild.id)
        track = self._selected_track(guild_id, last=False)
        active_key = self._active_radio_request.get(guild_id)
        if track is not None and active_key and self._track_key(track) == active_key:
            self._active_radio_request.pop(guild_id, None)
            log_event(
                "radio.request.skipped",
                guild_id=guild_id,
                track=self._track_data(track),
            )
            return
        await super()._mark_station_skip(ctx)

    async def _top_up_station_queue(self, guild_id: int) -> None:
        lock = self._station_top_up_locks.setdefault(int(guild_id), asyncio.Lock())
        async with lock:
            station = self.stations.get_active(guild_id)
            if station is None:
                log_event("radio.top_up.skipped", guild_id=guild_id, reason="no_active_station")
                return

            audio = self.bot.get_cog("Audio")
            guild = self.bot.get_guild(int(guild_id))
            author = self._active_voice_member_for_guild(guild) if guild is not None else None
            channel = self._best_text_channel(guild) if guild is not None else None
            if audio is None or guild is None or author is None or channel is None:
                log_event(
                    "radio.top_up.skipped",
                    guild_id=guild_id,
                    reason="missing_audio_or_guild_context",
                )
                return
            ctx = self._context_for(guild, author, channel)

            try:
                player = lavalink.get_player(guild_id)
            except (NodeNotFound, PlayerNotFound):
                log_event("radio.top_up.skipped", guild_id=guild_id, reason="no_player")
                return
            if len(player.queue) >= 2:
                log_event(
                    "radio.top_up.skipped",
                    guild_id=guild_id,
                    reason="queue_already_buffered",
                    queue_length=len(player.queue),
                )
                return

            seeds = [station["seed"]]
            if station.get("liked"):
                seeds.append(station["liked"][-1]["title"])
            if station.get("more_like"):
                seeds.append(station["more_like"][-1]["title"])
            recommended = await self._recommended_radio_track(station)
            query = (
                recommended["uri"]
                if recommended
                else await self._radio_fallback_query(random.choice(seeds))
            )
            log_event(
                "radio.top_up.play",
                guild_id=guild_id,
                station=station["name"],
                query=query,
                used_recommendation=bool(recommended),
                queue_length=len(player.queue),
                serialized=True,
            )
            await self._invoke_silently(audio.command_play, ctx, query=query)
