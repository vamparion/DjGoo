from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import discord
import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.command_catalog import command_tip
from voice.deck_store import DeckStore
from voice.now_playing_state import NowPlayingState
from voice.mini_player_protocol import MiniPlayerHistory
from voice.operational_log import log_event
from voice.queue_origin_ledger import QueueOriginLedger

from .audio_bridge import PlaybackControlsView
from .helpers import build_playback_control_embed
from .resilient_game_first_bridge import ResilientGameFirstDjGooAudioBridge


class ExperienceDjGooAudioBridge(ResilientGameFirstDjGooAudioBridge):
    """Present DjGoo as one persistent game-first control surface."""

    def __init__(self, *, bot, project_root: Path, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self.deck_store = DeckStore(project_root / "data" / "djgoo-decks.json")
        self.now_playing = NowPlayingState(
            project_root / "data" / "djgoo-now-playing.json"
        )
        self._deck_locks: dict[int, asyncio.Lock] = {}
        self._deck_render_state: dict[int, tuple[tuple[Any, ...], float]] = {}
        self._queue_item_ids: dict[int, str] = {}
        self._queue_undo: dict[int, dict[str, Any]] = {}
        self._muted_volumes: dict[int, int] = {}
        self._mini_command_depth = 0
        self.mini_history = MiniPlayerHistory(
            project_root / "data" / "djgoo-mini-history.json"
        )
        self.queue_origins = QueueOriginLedger(
            project_root / "data" / "djgoo-queue-origins.json"
        )

    async def _notice(self, description: str) -> None:
        if self._mini_command_depth > 0:
            log_event("mini_player.notice.suppressed", description=description[:500])
            return
        await super()._notice(description)

    async def handle(self, item: dict[str, Any]) -> Any:
        intent = str(item.get("intent") or "")
        if intent in {
            "mini_search",
            "mini_queue_remove",
            "mini_queue_move_next",
            "mini_queue_play_now",
            "mini_queue_reorder",
            "mini_queue_remove_many",
            "mini_queue_shuffle",
            "mini_queue_shuffle_requests",
            "mini_queue_clear",
            "mini_queue_undo",
            "mini_playlist_add",
            "mini_playlist_add_history",
            "mini_playlist_add_search",
            "mini_playlist_add_current",
            "mini_playlist_create",
            "mini_playlist_delete",
            "mini_playlist_remove_tracks",
            "mini_playlist_rename",
            "mini_playlist_reorder",
            "mini_radio_mode",
            "mini_stop_radio",
            "mini_mute",
            "mini_set_volume",
        }:
            result = await self._handle_mini_intent(item)
        else:
            result = await super().handle(item)
        if intent in {
            "mini_playlist_create",
            "mini_playlist_add",
            "mini_playlist_add_history",
            "mini_playlist_add_search",
            "mini_playlist_add_current",
            "mini_playlist_delete",
            "mini_playlist_remove_tracks",
            "mini_playlist_rename",
            "mini_playlist_reorder",
        }:
            for guild in getattr(self.bot, "guilds", []):
                self._publish_now_playing(int(guild.id))
        else:
            ctx = self._context()
            if ctx is not None and intent not in {"stop", "stop_radio"}:
                self._publish_now_playing(ctx.guild.id)
        return result

    def _stable_track_id(self, track: Any) -> str:
        identity = id(track)
        value = self._queue_item_ids.get(identity)
        if value is None:
            value = str(uuid.uuid4())
            self._queue_item_ids[identity] = value
        return value

    def _track_snapshot(
        self,
        track: Any,
        *,
        request: dict[str, Any] | None = None,
        request_type: str,
    ) -> dict[str, Any]:
        data = self._track_data(track)
        return {
            "id": self._stable_track_id(track),
            "title": str(data.get("title") or "Unknown track"),
            "artist": str(data.get("artist") or ""),
            "uri": str(data.get("uri") or ""),
            "artwork_url": str(data.get("artwork_url") or ""),
            "duration_seconds": int(data.get("duration_seconds") or 0),
            "requester": str((request or {}).get("requester_name") or ""),
            "requester_id": int((request or {}).get("requester_id") or 0),
            "request_timing": str((request or {}).get("timing") or ""),
            "request_type": request_type,
        }

    def _queue_snapshot(self, guild_id: int) -> list[dict[str, Any]]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return []
        ledger = getattr(self, "request_ledger", None)
        entries = ledger.entries(guild_id) if ledger is not None else []
        by_key: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_key.setdefault(str(entry.get("track_key") or ""), []).append(entry)
        origins_by_key: dict[str, list[dict[str, Any]]] = {}
        origin_ledger = getattr(self, "queue_origins", None)
        origin_entries = origin_ledger.entries(guild_id) if origin_ledger is not None else []
        for entry in origin_entries:
            origins_by_key.setdefault(str(entry.get("track_key") or ""), []).append(entry)
        station_active = self.stations.get_active(guild_id) is not None
        identity_counts: dict[str, int] = {}
        for track in [getattr(player, "current", None), *list(player.queue)]:
            if track is not None:
                identity = self._track_identity(track)
                identity_counts[identity] = identity_counts.get(identity, 0) + 1
        snapshot = []
        live_ids = set()
        for position, track in enumerate(list(player.queue), start=1):
            live_ids.add(id(track))
            requests = by_key.get(self._track_key(track), [])
            request = requests.pop(0) if requests else None
            origins = origins_by_key.get(self._track_key(track), [])
            origin = origins.pop(0) if origins else None
            if request is not None:
                request_type = "manual"
            elif origin and origin.get("source") == "playlist":
                request_type = f"playlist: {origin.get('label') or 'saved'}"
            elif station_active:
                request_type = "radio"
            else:
                request_type = str((origin or {}).get("source") or "automatic")
            item = self._track_snapshot(
                track,
                request=request,
                request_type=request_type,
            )
            item["position"] = position
            item["duplicate"] = identity_counts.get(self._track_identity(track), 0) > 1
            snapshot.append(item)
        current = getattr(player, "current", None)
        if current is not None:
            live_ids.add(id(current))
        self._queue_item_ids = {
            identity: identifier
            for identity, identifier in self._queue_item_ids.items()
            if identity in live_ids
        }
        return snapshot

    def _health_snapshot(self) -> dict[str, dict[str, Any]]:
        voice_path = self.project_root / "data" / "health" / "voice.json"
        try:
            voice = json.loads(voice_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            voice = {}
        try:
            voice_age = time.time() - float(voice.get("timestamp") or 0)
        except (TypeError, ValueError):
            voice_age = 999999.0
        return {
            "discord": {
                "ready": bool(self.bot.is_ready()),
                "label": "Discord",
            },
            "music_core": {
                "ready": any(
                    self._lavalink_node_ready(int(guild.id))
                    for guild in getattr(self.bot, "guilds", [])
                ),
                "label": "Music Core",
            },
            "voice": {
                "ready": bool(voice.get("ready")) and -5 <= voice_age <= 45,
                "label": "Voice",
            },
        }

    def _queue_track(self, guild_id: int, track_id: str) -> Any | None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return None
        for track in list(player.queue):
            if self._stable_track_id(track) == track_id:
                return track
        return None

    def _remember_queue(self, guild_id: int, player: Any) -> None:
        ledger = getattr(self, "request_ledger", None)
        self._queue_undo[int(guild_id)] = {
            "queue": list(player.queue),
            "requests": ledger.entries(guild_id) if ledger is not None else [],
        }

    def _mini_player_target(self) -> tuple[int, Any | None]:
        """Find DjGoo's player without requiring a human voice member."""

        latest = self.now_playing.latest() or {}
        guild_ids = []
        with contextlib.suppress(TypeError, ValueError):
            guild_ids.append(int(latest.get("guild_id") or 0))
        guild_ids.extend(
            int(guild.id)
            for guild in getattr(self.bot, "guilds", [])
            if int(getattr(guild, "id", 0) or 0)
        )
        seen = set()
        fallback: tuple[int, Any | None] = (0, None)
        for guild_id in guild_ids:
            if guild_id <= 0 or guild_id in seen:
                continue
            seen.add(guild_id)
            try:
                player = lavalink.get_player(guild_id)
            except (NodeNotFound, PlayerNotFound):
                player = None
            if fallback == (0, None):
                fallback = (guild_id, player)
            if player is not None and (
                getattr(player, "current", None) is not None
                or bool(getattr(player, "queue", []))
            ):
                return guild_id, player
        return fallback

    def _playlist_payload(self, **values: Any) -> dict[str, Any]:
        return {**values, "playlists": self.playlists.summaries()}

    def _state_track(self, *, current: bool, track_ids: set[str] | None = None) -> list[dict[str, Any]]:
        latest = self.now_playing.latest() or {}
        if current:
            track = latest.get("current")
            return [dict(track)] if isinstance(track, dict) else []
        queue = latest.get("queue") if isinstance(latest.get("queue"), list) else []
        selected = track_ids or set()
        return [
            dict(track)
            for track in queue
            if isinstance(track, dict) and str(track.get("id") or "") in selected
        ]

    async def _handle_mini_intent(self, item: dict[str, Any]) -> Any:
        intent = str(item.get("intent") or "")
        if intent == "mini_search":
            query = str(item.get("query") or "").strip()
            results = await self.search_candidates(query, limit=4)
            return {
                "status": "completed" if results else "failed",
                "message": f"Found {len(results)} clean match(es)." if results else "No clean song matches found.",
                "query": query,
                "results": results,
            }

        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}

        if intent == "mini_playlist_create":
            try:
                name, created = self.playlists.create(str(item.get("playlist") or ""))
            except ValueError as exc:
                return {"status": "failed", "message": str(exc)}
            return self._playlist_payload(
                status="completed",
                message=f"Created {name}." if created else f"{name} already exists.",
                playlist=name,
                created=created,
            )

        if intent == "mini_playlist_rename":
            try:
                old_name, name = self.playlists.rename(
                    str(item.get("playlist") or ""),
                    str(
                        item.get("value")
                        or payload.get("new_name")
                        or payload.get("name")
                        or ""
                    ),
                )
            except ValueError as exc:
                return {"status": "failed", "message": str(exc)}
            return self._playlist_payload(
                status="completed",
                message=f"Renamed {old_name} to {name}.",
                playlist=name,
            )

        if intent == "mini_playlist_delete":
            try:
                name = self.playlists.delete(str(item.get("playlist") or ""))
            except ValueError as exc:
                return {"status": "failed", "message": str(exc)}
            return self._playlist_payload(
                status="completed",
                message=f"Deleted {name}.",
                playlist="",
            )

        if intent == "mini_playlist_remove_tracks":
            try:
                name, removed = self.playlists.remove_tracks(
                    str(item.get("playlist") or ""),
                    [str(value) for value in payload.get("track_ids", [])],
                )
            except ValueError as exc:
                return {"status": "failed", "message": str(exc)}
            return self._playlist_payload(
                status="completed",
                message=f"Removed {removed} track(s) from {name}.",
                playlist=name,
                removed=removed,
            )

        if intent == "mini_playlist_reorder":
            try:
                name = self.playlists.reorder_tracks(
                    str(item.get("playlist") or ""),
                    [str(value) for value in payload.get("track_ids", [])],
                )
            except ValueError as exc:
                return {"status": "failed", "message": str(exc)}
            return self._playlist_payload(
                status="completed",
                message=f"Saved the order of {name}.",
                playlist=name,
            )

        if intent in {
            "mini_playlist_add_current",
            "mini_playlist_add",
            "mini_playlist_add_history",
            "mini_playlist_add_search",
        }:
            playlist = str(item.get("playlist") or "").strip()
            if not playlist:
                return {"status": "failed", "message": "Choose or create a playlist first."}
            selected_ids = {
                str(value)
                for value in payload.get("track_ids", [])
                if str(value).strip()
            }
            tracks: list[Any] = []
            if intent == "mini_playlist_add_current":
                _guild_id, player = self._mini_player_target()
                current = getattr(player, "current", None) if player is not None else None
                tracks = [current] if current is not None else self._state_track(current=True)
            elif intent == "mini_playlist_add":
                _guild_id, player = self._mini_player_target()
                if player is not None:
                    tracks = [
                        track
                        for track in list(getattr(player, "queue", []))
                        if self._stable_track_id(track) in selected_ids
                    ]
                if not tracks:
                    tracks = self._state_track(current=False, track_ids=selected_ids)
            elif intent == "mini_playlist_add_history":
                history_ids = {
                    str(value)
                    for value in payload.get("history_ids", [])
                    if str(value).strip()
                }
                tracks = [
                    track
                    for track in self.mini_history.entries()
                    if str(track.get("id") or "") in history_ids
                ]
            else:
                tracks = [
                    dict(track)
                    for track in payload.get("tracks", [])
                    if isinstance(track, dict)
                    and str(track.get("uri") or track.get("title") or "").strip()
                ]
            if not tracks:
                unavailable = {
                    "mini_playlist_add_current": "There is no current song to add.",
                    "mini_playlist_add": "Those queued songs are no longer available.",
                    "mini_playlist_add_history": "Those history songs are no longer available.",
                    "mini_playlist_add_search": "Those search results are no longer available.",
                }
                return {
                    "status": "failed",
                    "message": unavailable[intent],
                }
            added = 0
            duplicates = 0
            resolved_name = playlist
            for track in tracks:
                track_data = dict(track) if isinstance(track, dict) else self._track_data(track)
                result = self.playlists.add_track(playlist, track_data)
                resolved_name = result.playlist_name
                added += int(result.added)
                duplicates += int(not result.added)
            message = (
                f"Added {added} song(s) to {resolved_name}."
                if added
                else f"Already in {resolved_name}."
            )
            if added and duplicates:
                message += f" {duplicates} already there."
            return self._playlist_payload(
                status="completed",
                message=message,
                playlist=resolved_name,
                added=added,
                duplicates=duplicates,
            )

        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            return {"status": "failed", "message": "Join a voice channel before using playback controls."}
        guild_id = int(ctx.guild.id)

        if intent == "mini_radio_mode":
            station = self.stations.get_active(guild_id)
            if station is None:
                return {"status": "failed", "message": "Start a radio station first."}
            mode = str(item.get("value") or payload.get("mode") or "").lower()
            station = self.stations.set_mode(str(station.get("seed") or ""), mode)
            return {
                "status": "completed",
                "message": f"{station.get('name', 'Radio')} is now in {mode.title()} mode.",
                "mode": mode,
            }

        if intent == "mini_stop_radio":
            return await self._stop_radio_keep_requests(audio, ctx)

        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return {"status": "failed", "message": "The player is not connected yet."}

        if intent == "mini_mute":
            if int(getattr(player, "volume", 0) or 0) > 0:
                self._muted_volumes[guild_id] = int(player.volume)
                target = 0
                message = "Muted."
            else:
                target = self._muted_volumes.pop(guild_id, 100)
                message = f"Volume restored to {target}."
            await self._invoke_silently(audio.command_volume, ctx, vol=target)
            return {"status": "completed", "message": message, "volume": target}

        if intent == "mini_set_volume":
            target = max(0, min(150, int(item.get("value") or 0)))
            await self._invoke_silently(audio.command_volume, ctx, vol=target)
            return {"status": "completed", "message": f"Volume {target}.", "volume": target}

        if intent == "mini_queue_undo":
            previous = self._queue_undo.pop(guild_id, None)
            if previous is None:
                return {"status": "failed", "message": "There is no queue change to undo."}
            player.queue.clear()
            player.queue.extend(previous.get("queue", []))
            ledger = getattr(self, "request_ledger", None)
            if ledger is not None:
                ledger.replace_entries(guild_id, previous.get("requests", []))
            self._persist_player_state(guild_id, reason="mini_queue_undo")
            return {"status": "completed", "message": "Restored the previous queue."}

        if intent == "mini_queue_clear":
            self._remember_queue(guild_id, player)
            count = len(player.queue)
            player.queue.clear()
            ledger = getattr(self, "request_ledger", None)
            if ledger is not None:
                ledger.replace_entries(guild_id, [])
            self._persist_player_state(guild_id, reason="mini_queue_clear")
            return {"status": "completed", "message": f"Cleared {count} queued track(s)."}

        if intent in {"mini_queue_shuffle", "mini_queue_shuffle_requests"}:
            queue = list(player.queue)
            if len(queue) < 2:
                return {"status": "failed", "message": "There are fewer than two queued tracks to shuffle."}
            self._remember_queue(guild_id, player)
            random.shuffle(queue)
            player.queue.clear()
            player.queue.extend(queue)
            self._persist_player_state(guild_id, reason="mini_shuffle_queue")
            return {"status": "completed", "message": f"Shuffled {len(queue)} queued tracks."}

        if intent == "mini_queue_reorder":
            ordered_ids = [str(value) for value in payload.get("track_ids", [])]
            queue = list(player.queue)
            by_id = {self._stable_track_id(track): track for track in queue}
            if set(ordered_ids) != set(by_id) or len(ordered_ids) != len(queue):
                return {"status": "failed", "message": "The queue changed before the reorder could be applied. Refresh and try again."}
            self._remember_queue(guild_id, player)
            player.queue.clear()
            player.queue.extend(by_id[track_id] for track_id in ordered_ids)
            self._persist_player_state(guild_id, reason="mini_queue_reorder")
            return {"status": "completed", "message": "Queue order updated."}

        selected_ids = [str(value) for value in payload.get("track_ids", [])]
        track_id = str(payload.get("track_id") or item.get("value") or "")
        if track_id and track_id not in selected_ids:
            selected_ids.append(track_id)
        selected_id_set = set(selected_ids)
        selected = [
            track
            for track in list(player.queue)
            if self._stable_track_id(track) in selected_id_set
        ]
        if not selected:
            return {"status": "failed", "message": "That track is no longer in the queue."}

        self._remember_queue(guild_id, player)
        queue = list(player.queue)
        if intent in {"mini_queue_remove", "mini_queue_remove_many"}:
            queue = [
                track
                for track in queue
                if self._stable_track_id(track) not in selected_id_set
            ]
            ledger = getattr(self, "request_ledger", None)
            if ledger is not None:
                for track in selected:
                    ledger.consume(guild_id, self._track_key(track))
            message = f"Removed {len(selected)} queued track(s)."
        elif intent == "mini_queue_move_next":
            selected_track = selected[0]
            selected_id = self._stable_track_id(selected_track)
            queue = [
                track
                for track in queue
                if self._stable_track_id(track) != selected_id
            ]
            queue.insert(0, selected_track)
            message = f"Moved {getattr(selected_track, 'title', 'track')} next."
        elif intent == "mini_queue_play_now":
            selected_track = selected[0]
            selected_id = self._stable_track_id(selected_track)
            queue = [
                track
                for track in queue
                if self._stable_track_id(track) != selected_id
            ]
            queue.insert(0, selected_track)
            message = f"Playing {getattr(selected_track, 'title', 'track')} now."
        else:
            return {"status": "failed", "message": f"Unsupported Mini Player action: {intent}"}
        player.queue.clear()
        player.queue.extend(queue)
        if intent == "mini_queue_play_now":
            skipped = player.skip()
            if inspect.isawaitable(skipped):
                await skipped
        self._persist_player_state(guild_id, reason=intent)
        return {"status": "completed", "message": message}

    async def _stop_radio_keep_requests(self, audio: Any, ctx: Any) -> dict[str, Any]:
        guild_id = int(ctx.guild.id)
        station = self.stations.get_active(guild_id)
        if station is None:
            return {"status": "failed", "message": "Radio mode is already off."}
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            player = None
        ledger = getattr(self, "request_ledger", None)
        request_keys = ledger.pending_keys(guild_id) if ledger is not None else set()
        current = getattr(player, "current", None) if player is not None else None
        active_request_key = self._active_radio_request.get(guild_id)
        current_is_request = bool(
            current
            and (
                self._track_key(current) in request_keys
                or self._track_key(current) == active_request_key
            )
        )
        if player is not None:
            queued_tracks = list(getattr(player, "queue", []) or [])
            player.queue.clear()
            player.queue.extend(
                track
                for track in queued_tracks
                if self._track_key(track) in request_keys
            )
        self.stations.clear_active(guild_id)
        if not current_is_request:
            if player is not None and player.queue:
                skipped = player.skip()
                if inspect.isawaitable(skipped):
                    await skipped
            else:
                await self._invoke_silently(audio.command_stop, ctx)
        self._persist_player_state(guild_id, reason="mini_stop_radio")
        return {
            "status": "completed",
            "message": f"Stopped {station.get('name', 'radio')}. Requested music is preserved.",
        }

    def _mode_for_track(self, guild_id: int, track: Any) -> str:
        active_request = self._active_radio_request.get(int(guild_id))
        if active_request and self._track_key(track) == active_request:
            return "REQUEST"
        if self.stations.get_active(guild_id) is not None:
            return "RADIO"
        return "PLAYBACK"

    def _active_request_details(self, guild_id: int) -> dict[str, Any]:
        reader = getattr(self, "active_request_metadata", None)
        if callable(reader):
            value = reader(guild_id)
            if isinstance(value, dict):
                return value
        return {}

    def _queue_preview(self, guild_id: int) -> list[str]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return []
        return [
            str(getattr(track, "title", "") or "Unknown")
            for track in list(player.queue)[:3]
        ]

    def _tip_for_track(self, track: Any, *, radio_active: bool) -> str:
        key = self._track_key(track)
        index = (
            sum(key.encode("utf-8", errors="ignore"))
            if key
            else int(time.time())
        )
        hint = command_tip(index, radio_active=radio_active)
        return f"Try saying: “{hint.phrase}”"

    async def _send_playback_controls(
        self,
        guild,
        track,
        *,
        preferred_channel=None,
        force: bool = False,
    ) -> None:
        data = self._track_data(track)
        if self._should_reject_playing_track(data):
            log_event(
                "discord.deck.blocked_bad_track",
                guild_id=guild.id,
                track=data,
            )
            return
        channel = preferred_channel or self._best_text_channel(guild)
        if channel is None:
            log_event("discord.deck.no_channel", guild_id=guild.id)
            return
        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages:
            log_event(
                "discord.deck.missing_permission",
                guild_id=guild.id,
                channel_id=channel.id,
            )
            return

        station = self.stations.get_active(guild.id)
        mode = self._mode_for_track(guild.id, track)
        request = self._active_request_details(guild.id)
        queue_preview = self._queue_preview(guild.id)
        embed_data = build_playback_control_embed(
            data,
            station_name=station["name"] if station else None,
        )
        description = [f"Mode: **{mode}**"]
        if mode == "REQUEST":
            requester = str(request.get("requester_name") or "Player")
            timing = str(request.get("timing") or "next").title()
            description.append(f"Requested by: **{requester}** • {timing}")
        if station is not None:
            description.append(f"Station: **{station['name']}**")
        if queue_preview:
            description.append(f"Next: `{queue_preview[0]}`")
        uri = str(data.get("uri") or "").strip()
        if uri:
            description.append(f"[Open track]({uri})")
        description.append(
            "Use the controls below or keep playing without leaving your game."
        )
        embed_data["description"] = "\n".join(description)[:4096]
        embed_data["footer"] = {
            "text": self._tip_for_track(
                track,
                radio_active=station is not None,
            )
        }
        embed = discord.Embed.from_dict(embed_data)
        view = PlaybackControlsView(self, guild.id)
        content = (
            f"DjGoo • {mode} • {data.get('title', 'Unknown track')}"
        )[:2000]
        fingerprint = (
            self._track_key(track),
            mode,
            station.get("name", "") if station else "",
            str(request.get("requester_name") or ""),
            str(request.get("timing") or ""),
            tuple(queue_preview),
        )
        lock = self._deck_locks.setdefault(int(guild.id), asyncio.Lock())
        async with lock:
            previous = self._deck_render_state.get(int(guild.id))
            if previous is not None:
                previous_fingerprint, rendered_at = previous
                if previous_fingerprint == fingerprint and time.monotonic() - rendered_at < 10:
                    log_event(
                        "discord.deck.skipped_duplicate",
                        guild_id=guild.id,
                        mode=mode,
                        track=data,
                    )
                    return

            record = self.deck_store.get(guild.id)
            if record is not None:
                target_channel = guild.get_channel(int(record.get("channel_id") or 0))
                if target_channel is not None:
                    with contextlib.suppress(
                        discord.HTTPException,
                        discord.Forbidden,
                        discord.NotFound,
                    ):
                        message = await target_channel.fetch_message(
                            int(record.get("message_id") or 0)
                        )
                        await message.edit(content=content, embed=embed, view=view)
                        self._deck_render_state[int(guild.id)] = (
                            fingerprint,
                            time.monotonic(),
                        )
                        log_event(
                            "discord.deck.updated",
                            guild_id=guild.id,
                            channel_id=target_channel.id,
                            message_id=message.id,
                            mode=mode,
                            track=data,
                        )
                        return
                self.deck_store.clear(guild.id)

            try:
                message = await channel.send(
                    content=content,
                    embed=embed,
                    view=view,
                )
            except (discord.HTTPException, discord.Forbidden):
                log_event(
                    "discord.deck.failed",
                    guild_id=guild.id,
                    channel_id=getattr(channel, "id", None),
                    track=data,
                )
                return
            self.deck_store.set(
                guild.id,
                channel_id=channel.id,
                message_id=message.id,
            )
            self._deck_render_state[int(guild.id)] = (
                fingerprint,
                time.monotonic(),
            )
            log_event(
                "discord.deck.created",
                guild_id=guild.id,
                channel_id=channel.id,
                message_id=message.id,
                mode=mode,
                track=data,
            )

    def _publish_now_playing(
        self,
        guild_id: int,
        track: Any | None = None,
    ) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            player = None
        selected = track or (player.current if player is not None else None)
        if selected is None:
            self.now_playing.publish(
                guild_id,
                {
                    "schema_version": 2,
                    "playback_state": "idle",
                    "mode": "IDLE",
                    "title": "DjGoo is waiting for music",
                    "artist": "",
                    "uri": "",
                    "artwork_url": "",
                    "duration_seconds": 0,
                    "position_seconds": 0,
                    "started_at": 0,
                    "paused": False,
                    "volume": 0,
                    "station": "",
                    "station_details": None,
                    "requester": "",
                    "request_timing": "",
                    "current": None,
                    "queue": [],
                    "queue_count": 0,
                    "next_track": None,
                    "playlists": self.playlists.summaries(),
                    "history": self.mini_history.entries(),
                    "health": self._health_snapshot(),
                    "stale_after_seconds": 8,
                    "tip": "",
                },
            )
            return
        data = self._track_data(selected)
        station = self.stations.get_active(guild_id)
        mode = self._mode_for_track(guild_id, selected)
        request = self._active_request_details(guild_id)
        queue = self._queue_snapshot(guild_id)
        current = self._track_snapshot(
            selected,
            request=request,
            request_type=(
                "request"
                if mode == "REQUEST"
                else "radio"
                if mode == "RADIO"
                else "playback"
            ),
        )
        position = int(getattr(player, "position", 0) or 0)
        if position > max(10_000, int(current.get("duration_seconds") or 0) * 10):
            position //= 1000
        station_payload = None
        if station is not None:
            station_mode = str(station.get("mode") or "").strip().lower()
            if not station_mode:
                station_mode, _seed = self._split_radio_mode(str(station.get("seed") or ""))
            station_payload = {
                "id": str(station.get("id") or ""),
                "name": str(station.get("name") or ""),
                "seed": str(station.get("seed") or ""),
                "mode": station_mode,
                "reason": self._station_reason(station),
                "liked_count": len(station.get("liked", [])),
                "more_like_count": len(station.get("more_like", [])),
                "less_like_count": len(station.get("less_like", [])),
                "banned_count": len(station.get("banned", [])),
            }
        self.now_playing.publish(
            guild_id,
            {
                "schema_version": 2,
                "playback_state": "paused" if bool(getattr(player, "paused", False)) else "playing",
                "mode": mode,
                "title": current["title"],
                "artist": current["artist"],
                "uri": current["uri"],
                "artwork_url": current["artwork_url"],
                "duration_seconds": current["duration_seconds"],
                "position_seconds": max(0, position),
                "started_at": time.time(),
                "paused": bool(getattr(player, "paused", False)),
                "volume": int(getattr(player, "volume", 0) or 0),
                "station": station.get("name", "") if station else "",
                "station_details": station_payload,
                "requester": str(request.get("requester_name") or ""),
                "request_timing": str(request.get("timing") or ""),
                "current": current,
                "queue": queue,
                "queue_count": len(queue),
                "next_track": queue[0] if queue else None,
                "playlists": self.playlists.summaries(),
                "history": self.mini_history.entries(),
                "health": self._health_snapshot(),
                "stale_after_seconds": 8,
                "tip": self._tip_for_track(
                    selected,
                    radio_active=station is not None,
                ),
            },
        )

    async def handle_track_start(self, guild, track) -> None:
        origin_ledger = getattr(self, "queue_origins", None)
        if origin_ledger is not None:
            origin_ledger.consume(int(guild.id), self._track_key(track))
        await super().handle_track_start(guild, track)
        # The lower bridge classifies a track as REQUEST during its station-start
        # hook, which runs after the first deck update. Refresh once more so the
        # persistent deck and Mini Player immediately show the correct mode.
        await self._send_playback_controls(guild, track, force=True)
        data = self._track_data(track)
        station = self.stations.get_active(guild.id)
        self.mini_history.add(
            {
                **data,
                "id": self._stable_track_id(track),
            },
            mode=self._mode_for_track(guild.id, track),
            station=str((station or {}).get("name") or ""),
        )
        self._publish_now_playing(guild.id, track)

    async def handle_track_enqueue(self, guild, track) -> None:
        await super().handle_track_enqueue(guild, track)
        self._publish_now_playing(guild.id)

    async def _stop_radio(self, audio, ctx) -> str:
        result = await super()._stop_radio(audio, ctx)
        self.now_playing.clear(ctx.guild.id)
        return result

    async def _stop_playback(self, audio, ctx) -> str:
        result = await super()._stop_playback(audio, ctx)
        self.now_playing.clear(ctx.guild.id)
        return result
