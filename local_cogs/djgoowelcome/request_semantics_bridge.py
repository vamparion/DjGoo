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
        if not self._should_resume_playback():
            self.request_ledger.clear_all()
            self.queue_origins.clear_all()
        self._pending_request_context: dict[int, dict[str, Any]] = {}
        self._active_request_metadata: dict[int, dict[str, Any]] = {}
        self._station_enqueue_depth: dict[int, int] = {}

    def _request_metadata(
        self,
        ctx: Any,
        *,
        timing: str,
        item: Dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        author = getattr(ctx, "author", None)
        command = item or {}
        requester_id = int(getattr(author, "id", 0) or 0)
        requester_key = str(
            command.get("profile_id")
            or command.get("device_id")
            or requester_id
            or "anonymous"
        )
        return {
            "timing": timing,
            "requester_id": requester_id,
            "requester_name": str(
                command.get("username")
                or command.get("requester_name")
                or
                getattr(author, "display_name", "")
                or getattr(author, "name", "")
                or "Player"
            )[:100],
            "requester_key": requester_key,
            "role": str(command.get("actor_role") or "member"),
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
            item=item,
        )
        self._pending_request_context[guild_id]["source"] = str(
            item.get("source") or "unknown"
        )
        requester_key = str(self._pending_request_context[guild_id]["requester_key"])
        if self.gaming.queue_limit_reached(
            guild_id,
            requester_key,
            self.request_ledger.entries(guild_id),
        ):
            limit = self.gaming.settings(guild_id)["per_user_queue_limit"]
            return {
                "status": "rejected",
                "message": f"Your DjGoo queue limit is {limit} songs. Let one play before adding another.",
            }
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
    ) -> Any:
        if not query:
            await self._notice("Tell me which song to request.")
            return "Missing request query"
        resolved = await self._resolve_play_queries(
            query,
            source=source,
        )
        if not resolved:
            pending_store = getattr(self, "pending_choices", None)
            pending = pending_store.get() if pending_store is not None else None
            if isinstance(pending, dict) and str(pending.get("query") or "") == query:
                self._lifecycle_transition(
                    ctx.guild.id,
                    "failed",
                    reason="DjGoo needs a player choice before playback can begin",
                )
                return {
                    "status": "failed",
                    "message": "Choose one of the four matching songs within 15 seconds.",
                }
            await self._notice(
                "I could not find a clean playable version of that request."
            )
            return "No clean request"
        resolved_query = resolved[0]
        explicit = bool(getattr(self, "_resolved_track_explicit", lambda _uri: False)(resolved_query))
        explicit_policy = self.gaming.settings(ctx.guild.id)["explicit_policy"]
        if explicit and explicit_policy == "reject":
            return {
                "status": "rejected",
                "message": "DjGoo blocked that explicit track for this session.",
            }
        if explicit and explicit_policy == "warn":
            await self._notice("Explicit track warning: this request contains explicit lyrics.")
        station = self.stations.get_active(ctx.guild.id)

        if not await self._wait_for_lavalink_node(ctx.guild.id):
            await self._notice(
                "The request was not queued because the Audio Engine is unavailable."
            )
            return "Request startup failed"

        self._lifecycle_transition(
            ctx.guild.id,
            "loading",
            reason="Clean track resolved; sending to player",
        )

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

        requested_key = self._track_key(requested_track)
        self._lifecycle_transition(
            ctx.guild.id,
            "queued",
            reason="Player confirmed queue entry",
            track=self._track_data(requested_track),
            track_key=requested_key,
        )

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
        else:
            metadata = self._pending_request_context.get(int(ctx.guild.id), {})
            data = self._track_data(requested_track)
            self.request_ledger.add(
                ctx.guild.id,
                track_key=requested_key,
                title=str(data.get("title") or ""),
                timing=timing,
                requester_id=int(metadata.get("requester_id") or 0),
                requester_name=str(metadata.get("requester_name") or ""),
                requester_key=str(metadata.get("requester_key") or ""),
                entry_id=self._stable_track_id(requested_track),
                lane="request",
                insertion_reason=f"{timing} request",
                source=source,
            )
        self._apply_request_fairness(ctx.guild.id, force_front=timing == "now")

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

        requester_key = str(requester_id or "discord")
        if self.gaming.queue_limit_reached(
            guild_id,
            requester_key,
            self.request_ledger.entries(guild_id),
        ):
            try:
                player = lavalink.get_player(guild_id)
                player.queue.remove(track)
            except (NodeNotFound, PlayerNotFound, ValueError):
                pass
            await self._notice(
                f"{requester_name} already has the maximum number of pending requests."
            )
            log_event(
                "request.native_discord.limit_rejected",
                guild_id=guild_id,
                requester_id=requester_id,
                requester_name=requester_name,
            )
            self._publish_now_playing(guild_id)
            return

        if self.stations.get_active(guild_id) is not None:
            super()._remember_radio_request(guild_id, track)
        data = self._track_data(track)
        self.request_ledger.add(
            guild_id,
            track_key=track_key,
            title=str(data.get("title") or ""),
            timing="next",
            requester_id=requester_id,
            requester_name=requester_name,
            entry_id=self._stable_track_id(track),
            lane="request",
            insertion_reason="Discord manual request",
            source="discord",
            requester_key=requester_key,
        )
        self._place_request_before_radio(
            guild_id,
            track,
            force_front=force_front,
        )
        self._apply_request_fairness(guild_id, force_front=force_front)
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
            entry_id=self._stable_track_id(track),
            lane="request",
            insertion_reason=f"{str(metadata.get('timing') or 'next')} request",
            source=str(metadata.get("source") or "unknown"),
            requester_key=str(metadata.get("requester_key") or ""),
        )

    def _apply_request_fairness(self, guild_id: int, *, force_front: bool = False) -> None:
        if force_front or not self.gaming.settings(guild_id)["round_robin"]:
            return
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        queue = list(player.queue)
        requests = self.request_ledger.entries(guild_id)
        by_track_key: dict[str, list[dict[str, Any]]] = {}
        for entry in requests:
            by_track_key.setdefault(str(entry.get("track_key") or ""), []).append(entry)
        request_tracks: dict[str, Any] = {}
        request_entries: list[dict[str, Any]] = []
        program_tracks: list[Any] = []
        for track in queue:
            entries = by_track_key.get(self._track_key(track), [])
            entry = entries.pop(0) if entries else None
            if entry is None:
                program_tracks.append(track)
                continue
            entry_id = str(entry.get("entry_id") or self._stable_track_id(track))
            entry = {**entry, "entry_id": entry_id}
            request_entries.append(entry)
            request_tracks[entry_id] = track
        ordered_ids = self.gaming.fair_order(request_entries)
        player.queue.clear()
        player.queue.extend(request_tracks[entry_id] for entry_id in ordered_ids if entry_id in request_tracks)
        player.queue.extend(program_tracks)

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
