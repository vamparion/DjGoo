from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

import discord
import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.command_catalog import COMMAND_HINTS, command_tip
from voice.deck_store import DeckStore
from voice.now_playing_state import NowPlayingState
from voice.operational_log import log_event

from .audio_bridge import PlaybackControlsView
from .helpers import build_playback_control_embed
from .resilient_game_first_bridge import ResilientGameFirstDjGooAudioBridge


class ExperienceDjGooAudioBridge(ResilientGameFirstDjGooAudioBridge):
    """Present DjGoo as one persistent game-first control surface."""

    def __init__(self, *, bot, project_root: Path, send_payload):
        super().__init__(bot=bot, project_root=project_root, send_payload=send_payload)
        self.deck_store = DeckStore(project_root / "data" / "djgoo-decks.json")
        self.now_playing = NowPlayingState(project_root / "data" / "djgoo-now-playing.json")

    def _mode_for_track(self, guild_id: int, track: Any) -> str:
        active_request = self._active_radio_request.get(int(guild_id))
        if active_request and self._track_key(track) == active_request:
            return "REQUEST"
        if self.stations.get_active(guild_id) is not None:
            return "RADIO"
        return "PLAYBACK"

    def _queue_preview(self, guild_id: int) -> list[str]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return []
        return [str(getattr(track, "title", "") or "Unknown") for track in list(player.queue)[:3]]

    def _tip_for_track(self, track: Any, *, radio_active: bool) -> str:
        key = self._track_key(track)
        index = sum(key.encode("utf-8", errors="ignore")) if key else int(time.time())
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
            log_event("discord.deck.blocked_bad_track", guild_id=guild.id, track=data)
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
        queue_preview = self._queue_preview(guild.id)
        embed_data = build_playback_control_embed(
            data,
            station_name=station["name"] if station else None,
        )
        description = [f"Mode: **{mode}**"]
        if station is not None:
            description.append(f"Station: **{station['name']}**")
        if queue_preview:
            description.append(f"Next: `{queue_preview[0]}`")
        uri = str(data.get("uri") or "").strip()
        if uri:
            description.append(f"[Open track]({uri})")
        description.append("Use the controls below or keep playing without leaving your game.")
        embed_data["description"] = "\n".join(description)[:4096]
        embed_data["footer"] = {
            "text": self._tip_for_track(track, radio_active=station is not None)
        }
        embed = discord.Embed.from_dict(embed_data)
        view = PlaybackControlsView(self, guild.id)
        content = f"DjGoo • {mode} • {data.get('title', 'Unknown track')}"[:2000]

        record = self.deck_store.get(guild.id)
        if record is not None:
            target_channel = guild.get_channel(int(record.get("channel_id") or 0))
            if target_channel is not None:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
                    message = await target_channel.fetch_message(
                        int(record.get("message_id") or 0)
                    )
                    await message.edit(content=content, embed=embed, view=view)
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
            message = await channel.send(content=content, embed=embed, view=view)
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
        log_event(
            "discord.deck.created",
            guild_id=guild.id,
            channel_id=channel.id,
            message_id=message.id,
            mode=mode,
            track=data,
        )

    def _publish_now_playing(self, guild_id: int, track: Any | None = None) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        selected = track or player.current
        if selected is None:
            return
        data = self._track_data(selected)
        station = self.stations.get_active(guild_id)
        mode = self._mode_for_track(guild_id, selected)
        self.now_playing.publish(
            guild_id,
            {
                "mode": mode,
                "title": data.get("title", "Unknown track"),
                "artist": data.get("artist", ""),
                "uri": data.get("uri", ""),
                "duration_seconds": int(data.get("duration_seconds") or 0),
                "started_at": time.time(),
                "paused": bool(getattr(player, "paused", False)),
                "volume": int(getattr(player, "volume", 0) or 0),
                "station": station.get("name", "") if station else "",
                "queue": self._queue_preview(guild_id),
                "tip": self._tip_for_track(selected, radio_active=station is not None),
            },
        )

    async def handle_track_start(self, guild, track) -> None:
        await super().handle_track_start(guild, track)
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
