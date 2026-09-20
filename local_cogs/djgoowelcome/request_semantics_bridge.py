from __future__ import annotations

from typing import Any, Dict

import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.operational_log import log_event
from voice.request_ledger import RequestLedger

from .experience_audio_bridge import ExperienceDjGooAudioBridge


class RequestSemanticsDjGooAudioBridge(ExperienceDjGooAudioBridge):
    """Implement explicit request timing while radio remains active."""

    def __init__(self, *, bot, project_root, send_payload):
        super().__init__(
            bot=bot,
            project_root=project_root,
            send_payload=send_payload,
        )
        self.request_ledger = RequestLedger(
            project_root / "data" / "djgoo-requests.json"
        )
        self._pending_request_context: dict[int, dict[str, Any]] = {}
        self._active_request_metadata: dict[int, dict[str, Any]] = {}
        self._station_enqueue_depth: dict[int, int] = {}

    def _request_metadata(
        self,
        ctx: Any,
        *,
        timing: str,
    ) -> dict[str, Any]:
        author = getattr(ctx, "author", None)
        return {
            "timing": timing,
            "requester_id": int(getattr(author, "id", 0) or 0),
            "requester_name": str(
                getattr(author, "display_name", "")
                or getattr(author, "name", "")
                or "Player"
            )[:100],
        }

    async def handle(self, item: Dict[str, Any]) -> str:
        intent = str(item.get("intent") or "")
        if intent not in {"play", "play_now", "queue_request"}:
            return await super().handle(item)

        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            return await super().handle(item)

        timing = {
            "play": "next",
            "play_now": "now",
            "queue_request": "later",
        }[intent]
        guild_id = int(ctx.guild.id)
        self._pending_request_context[guild_id] = self._request_metadata(
            ctx,
            timing=timing,
        )
        try:
            if intent == "play":
                return await super().handle(item)
            return await self._handle_timed_request(
                audio,
                ctx,
                query=str(item.get("query") or "").strip(),
                source=str(item.get("source") or ""),
                timing=timing,
            )
        finally:
            self._pending_request_context.pop(guild_id, None)

    async def _handle_timed_request(
        self,
        audio: Any,
        ctx: Any,
        *,
        query: str,
        source: str,
        timing: str,
    ) -> str:
        if not query:
            await self._notice("Tell me which song to request.")
            return "Missing request query"
        resolved = await self._resolve_play_queries(
            query,
            source=source,
        )
        if not resolved:
            await self._notice(
                "I could not find a clean playable version of that request."
            )
            return "No clean request"
        resolved_query = resolved[0]
        station = self.stations.get_active(ctx.guild.id)

        if not await self._wait_for_lavalink_node(ctx.guild.id):
            await self._notice(
                "The request was not queued because the Audio Engine is unavailable."
            )
            return "Request startup failed"

        if source == "mini_player" and self._mini_player_has_track(
            ctx.guild.id,
            resolved_query,
        ):
            message = "That song is already playing or queued."
            log_event(
                "request.mini_player.duplicate_rejected",
                guild_id=ctx.guild.id,
                timing=timing,
                query=query,
                resolved_query=resolved_query,
            )
            return message

        _prior_queue_ids, prior_track_ids = self._player_identity_snapshot(
            ctx.guild.id
        )
        if timing == "now":
            bumpplay = getattr(audio, "command_bumpplay", None)
            if bumpplay is not None:
                await self._invoke_silently(
                    bumpplay,
                    ctx,
                    play_now=True,
                    query=resolved_query,
                )
            else:
                await self._invoke_silently(
                    audio.command_play,
                    ctx,
                    query=resolved_query,
                )
                self._promote_new_queue_entries(
                    ctx.guild.id,
                    prior_track_ids,
                )
                try:
                    player = lavalink.get_player(ctx.guild.id)
                    result = player.skip()
                    if hasattr(result, "__await__"):
                        await result
                except (NodeNotFound, PlayerNotFound):
                    pass
        else:
            await self._invoke_silently(
                audio.command_play,
                ctx,
                query=resolved_query,
            )

        requested_track = await self._requested_track_after_enqueue(
            ctx.guild.id,
            prior_track_ids=prior_track_ids,
        )
        if requested_track is None:
            await self._notice(
                "The Music Core did not add that request, so the queue was unchanged."
            )
            return "Request enqueue failed"

        if station is not None:
            self._remember_radio_request(
                ctx.guild.id,
                requested_track,
            )
            if timing == "later":
                self._place_request_before_radio(
                    ctx.guild.id,
                    requested_track,
                    force_front=False,
                )

        data = self._track_data(requested_track)
        display = data.get("title") or query
        self._persist_player_state(
            ctx.guild.id,
            reason=f"request_{timing}_enqueued",
        )
        if timing == "now":
            notice = f"Playing `{display}` now."
        elif timing == "later":
            notice = f"Added `{display}` after existing player requests."
        else:
            notice = f"Queued `{display}` next."
        if station is not None:
            notice += (
                f" `{station.get('name', 'Radio')}` continues afterward."
            )
        await self._notice(notice)
        log_event(
            "request.timed.queued",
            guild_id=ctx.guild.id,
            timing=timing,
            station=(station or {}).get("name"),
            track=data,
            source=source,
        )
        return notice

    def _mini_player_has_track(self, guild_id: int, resolved_query: str) -> bool:
        """Keep UI retries from silently adding the same track more than once."""
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return False
        requested_identity = self._track_identity({"uri": resolved_query})
        if not requested_identity:
            return False
        tracks = [getattr(player, "current", None), *list(player.queue)]
        return any(
            track is not None and self._track_identity(track) == requested_identity
            for track in tracks
        )

    async def _top_up_station_queue(self, guild_id: int) -> None:
        numeric_guild_id = int(guild_id)
        self._station_enqueue_depth[numeric_guild_id] = (
            self._station_enqueue_depth.get(numeric_guild_id, 0) + 1
        )
        try:
            await super()._top_up_station_queue(numeric_guild_id)
        finally:
            remaining = self._station_enqueue_depth.get(numeric_guild_id, 1) - 1
            if remaining > 0:
                self._station_enqueue_depth[numeric_guild_id] = remaining
            else:
                self._station_enqueue_depth.pop(numeric_guild_id, None)

    async def handle_track_enqueue(self, guild: Any, track: Any) -> None:
        await super().handle_track_enqueue(guild, track)
        guild_id = int(guild.id)
        if self.stations.get_active(guild_id) is None:
            return
        if self._station_enqueue_depth.get(guild_id, 0) > 0:
            return
        if guild_id in self._pending_request_context:
            return

        track_key = self._track_key(track)
        if not track_key or track_key in self.request_ledger.pending_keys(guild_id):
            return

        requester = getattr(track, "requester", None)
        requester_id = int(getattr(requester, "id", requester or 0) or 0)
        bot_user_id = int(getattr(getattr(self.bot, "user", None), "id", 0) or 0)
        if requester_id and requester_id == bot_user_id:
            return
        requester_name = str(
            getattr(requester, "display_name", "")
            or getattr(requester, "name", "")
            or "Discord player"
        )[:100]
        extras = getattr(track, "extras", {}) or {}
        try:
            force_front = bool(extras.get("bumped"))
        except AttributeError:
            force_front = False

        super()._remember_radio_request(guild_id, track)
        data = self._track_data(track)
        self.request_ledger.add(
            guild_id,
            track_key=track_key,
            title=str(data.get("title") or ""),
            timing="next",
            requester_id=requester_id,
            requester_name=requester_name,
        )
        self._place_request_before_radio(
            guild_id,
            track,
            force_front=force_front,
        )
        self._persist_player_state(
            guild_id,
            reason="native_discord_request_enqueued",
        )
        self._publish_now_playing(guild_id)
        log_event(
            "request.native_discord.detected",
            guild_id=guild_id,
            requester_id=requester_id,
            requester_name=requester_name,
            force_front=force_front,
            track=data,
        )

    def _player_identity_snapshot(
        self,
        guild_id: int,
    ) -> tuple[set[int], set[int]]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return set(), set()
        queue_ids = {id(track) for track in list(player.queue)}
        track_ids = set(queue_ids)
        if player.current is not None:
            track_ids.add(id(player.current))
        return queue_ids, track_ids

    def _place_request_before_radio(
        self,
        guild_id: int,
        requested_track: Any,
        *,
        force_front: bool,
    ) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        queue = list(player.queue)
        if requested_track not in queue:
            return
        queue.remove(requested_track)
        if force_front:
            insert_at = 0
        else:
            known_request_keys = self.request_ledger.pending_keys(guild_id)
            insert_at = 0
            for index, queued_track in enumerate(queue):
                if self._track_key(queued_track) not in known_request_keys:
                    insert_at = index
                    break
                insert_at = index + 1
        queue.insert(insert_at, requested_track)
        player.queue.clear()
        player.queue.extend(queue)

    def _remember_radio_request(
        self,
        guild_id: int,
        track: Any,
    ) -> None:
        super()._remember_radio_request(guild_id, track)
        metadata = self._pending_request_context.get(
            int(guild_id),
            {},
        )
        data = self._track_data(track)
        self.request_ledger.add(
            guild_id,
            track_key=self._track_key(track),
            title=str(data.get("title") or ""),
            timing=str(metadata.get("timing") or "next"),
            requester_id=int(metadata.get("requester_id") or 0),
            requester_name=str(metadata.get("requester_name") or ""),
        )

    def _consume_radio_request(
        self,
        guild_id: int,
        track: Any,
    ) -> bool:
        remembered = super()._consume_radio_request(guild_id, track)
        metadata = self.request_ledger.consume(
            guild_id,
            self._track_key(track),
        )
        if metadata is not None:
            self._active_request_metadata[int(guild_id)] = metadata
        else:
            self._active_request_metadata.pop(int(guild_id), None)
        return remembered or metadata is not None

    def active_request_metadata(
        self,
        guild_id: int,
    ) -> dict[str, Any] | None:
        value = self._active_request_metadata.get(int(guild_id))
        return dict(value) if isinstance(value, dict) else None
