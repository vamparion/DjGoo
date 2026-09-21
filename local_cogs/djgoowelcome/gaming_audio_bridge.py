from __future__ import annotations

import asyncio
import math
from typing import Any, Dict

import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.mini_player_protocol import result_failed
from voice.operational_log import log_event

from .profile_audio_bridge import ProfileDjGooAudioBridge


VOTE_INTENTS = {
    "skip": "skip",
    "station_more_like_current": "more_like",
    "station_less_like_current": "less_like",
    "station_ban_current": "ban",
}


class GamingDjGooAudioBridge(ProfileDjGooAudioBridge):
    """Apply shared game-session policy to every playback control surface."""

    def __init__(self, *, bot, project_root, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self._transition_tasks: dict[int, asyncio.Task] = {}

    async def handle(self, item: Dict[str, Any]) -> Any:
        intent = str(item.get("intent") or "")
        if intent in {"mini_queue_remove", "mini_queue_remove_many", "mini_queue_clear", "mini_queue_reorder"}:
            ctx = self._context()
            if ctx is not None and not self.gaming.can_direct_control(self._actor_role(item, ctx)):
                return {
                    "status": "rejected",
                    "message": "A DjGoo moderator is required for that queue change.",
                }
        if intent == "gaming_undo":
            return await self._undo_last_action()
        vote_action = VOTE_INTENTS.get(intent)
        if vote_action is not None:
            vote = self._vote_result(item, vote_action)
            if vote is not None and not vote.execute:
                return {
                    "status": "pending",
                    "message": f"{vote_action.replace('_', ' ').title()} vote {vote.votes}/{vote.threshold}.",
                }
        if intent == "skip":
            self._remember_current_for_undo("skip")
        elif intent == "station_ban_current":
            self._remember_current_for_undo("ban")
        return await super().handle(item)

    def _actor_role(self, item: Dict[str, Any], ctx: Any) -> str:
        configured = str(item.get("actor_role") or "")
        if configured:
            return configured
        member = getattr(ctx, "author", None)
        guild = getattr(ctx, "guild", None)
        permissions = getattr(member, "guild_permissions", None)
        if guild is not None and int(getattr(member, "id", 0) or 0) == int(getattr(guild, "owner_id", 0) or 0):
            return "host"
        if bool(getattr(permissions, "manage_guild", False)):
            return "moderator"
        return "member"

    def _vote_result(self, item: Dict[str, Any], action: str):
        ctx = self._context()
        if ctx is None:
            return None
        role = self._actor_role(item, ctx)
        current = self._selected_track(ctx.guild.id, last=False)
        track_key = self._track_key(current) if current is not None else "nothing-playing"
        voter_key = str(
            item.get("profile_id")
            or item.get("device_id")
            or getattr(getattr(ctx, "author", None), "id", 0)
            or "anonymous"
        )
        result = self.gaming.cast_vote(
            ctx.guild.id,
            track_key=track_key,
            action=action,
            voter_key=voter_key,
            role=role,
        )
        log_event(
            "gaming.vote",
            guild_id=ctx.guild.id,
            action=action,
            role=role,
            votes=result.votes,
            threshold=result.threshold,
            execute=result.execute,
        )
        return result

    async def handle_gaming_button(self, interaction: Any, intent: str) -> str | None:
        if intent not in VOTE_INTENTS:
            return None
        ctx = self._context_for(interaction.guild, interaction.user, interaction.channel)
        item = {
            "intent": intent,
            "source": "button",
            "device_id": f"discord:{interaction.user.id}",
            "actor_role": self._actor_role({}, ctx),
        }
        result = self._vote_result(item, VOTE_INTENTS[intent])
        if result is not None and not result.execute:
            return f"Vote recorded ({result.votes}/{result.threshold})."
        return None

    def _remember_current_for_undo(self, action: str) -> None:
        ctx = self._context()
        if ctx is None:
            return
        track = self._selected_track(ctx.guild.id, last=False)
        if track is None:
            return
        payload = {"track": self._track_data(track)}
        station = self.stations.get_active(ctx.guild.id)
        if station is not None:
            payload["station_seed"] = station.get("seed", "")
        self.gaming.record_undo(ctx.guild.id, action, payload)

    async def _undo_last_action(self) -> Any:
        ctx = self._context()
        audio = self.bot.get_cog("Audio")
        if ctx is None or audio is None:
            return {"status": "failed", "message": "DjGoo has no active player to undo."}
        item = self.gaming.pop_undo(ctx.guild.id)
        if item is None:
            return {"status": "failed", "message": "There is no recent action to undo."}
        action = str(item.get("action") or "")
        if action == "queue":
            return await self._handle_mini_intent({"intent": "mini_queue_undo"})
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
        if action == "ban":
            station = self.stations.get_active(ctx.guild.id)
            if station is None:
                return {"status": "failed", "message": "That station is no longer active."}
            self.stations.remove_feedback(station["seed"], "banned", track)
            return {"status": "completed", "message": "Undid the last station ban."}
        query = str(track.get("uri") or track.get("title") or "")
        if action == "skip" and query:
            result = await super().handle(
                {"intent": "play_now", "query": query, "source": "undo", "actor_role": "host"}
            )
            return {
                "status": "failed" if result_failed(result) else "completed",
                "message": "Restored the skipped track." if not result_failed(result) else str(result),
            }
        return {"status": "failed", "message": "That action can no longer be undone."}

    async def handle_track_start(self, guild: Any, track: Any) -> None:
        await super().handle_track_start(guild, track)
        self.gaming.clear_track_votes(guild.id, self._track_key(track))
        settings = self.gaming.settings(guild.id)
        target_volume = self._normalized_volume(track, int(settings["normalization_target"]))
        if settings["volume_normalization"]:
            await self._set_player_volume(guild.id, target_volume)
        prior = self._transition_tasks.pop(int(guild.id), None)
        if prior is not None:
            prior.cancel()
        if settings["crossfade_enabled"]:
            self._transition_tasks[int(guild.id)] = asyncio.create_task(
                self._run_fade_transition(guild.id, int(settings["crossfade_seconds"]))
            )
        if settings["preload_enabled"] and self.stations.get_active(guild.id) is not None:
            await self._top_up_station_queue(guild.id)

    async def handle_track_end(self, guild: Any, track: Any) -> None:
        task = self._transition_tasks.pop(int(guild.id), None)
        if task is not None:
            task.cancel()
        await super().handle_track_end(guild, track)

    async def _set_player_volume(self, guild_id: int, volume: int) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        setter = getattr(player, "set_volume", None)
        if callable(setter):
            result = setter(max(0, min(150, int(volume))))
            if hasattr(result, "__await__"):
                await result

    def _normalized_volume(self, track: Any, target: int) -> int:
        info = getattr(track, "info", {}) or {}
        gain = info.get("replayGain") or info.get("replay_gain") or info.get("gain_db")
        try:
            adjusted = float(target) * math.pow(10.0, float(gain) / 20.0)
        except (TypeError, ValueError):
            adjusted = float(target)
        return max(20, min(150, round(adjusted)))

    async def _run_fade_transition(self, guild_id: int, seconds: int) -> None:
        try:
            player = lavalink.get_player(guild_id)
            duration = int(getattr(getattr(player, "current", None), "length", 0) or 0) / 1000
            if duration <= seconds + 5:
                return
            await asyncio.sleep(max(0.0, duration - seconds))
            initial = int(getattr(player, "volume", 100) or 100)
            for step in range(1, 5):
                await self._set_player_volume(guild_id, round(initial * (1 - step / 4)))
                await asyncio.sleep(seconds / 4)
        except (asyncio.CancelledError, NodeNotFound, PlayerNotFound):
            return
