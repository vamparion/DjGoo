from __future__ import annotations

import contextlib
import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import discord
import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.djgoo_playlists import DjGooPlaylists
from voice.djgoo_stations import DjGooStations

from .helpers import (
    PLAYBACK_CONTROL_BUTTONS,
    build_playback_control_embed,
    build_station_track_payload,
    load_secrets,
)


log = logging.getLogger("red.djgoowelcome.audio_bridge")


class _NoopTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCommand:
    def reset_cooldown(self, ctx):
        return None


class _FakeMessage:
    id = 0
    attachments = []

    async def add_reaction(self, reaction):
        return None

    async def delete(self):
        return None

    async def edit(self, **kwargs):
        return self


class DjGooAudioContext:
    def __init__(self, *, bot, guild, author, channel, send_payload: Callable[[Dict[str, Any]], Any]):
        self.bot = bot
        self.guild = guild
        self.author = author
        self.channel = channel
        self.me = guild.me
        self.clean_prefix = "!"
        self.prefix = "!"
        self.command = _FakeCommand()
        self.invoked_subcommand = None
        self.message = _FakeMessage()
        self._send_payload = send_payload

    def typing(self):
        return _NoopTyping()

    async def send(self, content=None, **kwargs):
        payload: Dict[str, Any] = {"username": "DjGoo"}
        if content:
            payload["content"] = str(content)
        embeds = []
        embed = kwargs.get("embed")
        if embed is not None:
            embeds.append(embed.to_dict() if hasattr(embed, "to_dict") else embed)
        for item in kwargs.get("embeds") or []:
            embeds.append(item.to_dict() if hasattr(item, "to_dict") else item)
        if embeds:
            payload["embeds"] = embeds
        await self._send_payload(payload)
        return _FakeMessage()

    async def send_help(self, command=None):
        await self.send("DjGoo could not show that interactive help here.")

    async def tick(self, *, message: Optional[str] = None):
        await self.send(message or "OK")
        return True

    async def invoke(self, command, *args, **kwargs):
        callback = getattr(command, "callback", None)
        if callback is None:
            return await command(self, *args, **kwargs)
        bound_self = getattr(callback, "__self__", None)
        if bound_self is not None:
            return await callback(self, *args, **kwargs)
        cog = self.bot.get_cog("Audio")
        return await callback(cog, self, *args, **kwargs)


class PlaybackControlsView(discord.ui.View):
    def __init__(self, bridge: "DjGooAudioBridge", guild_id: int):
        super().__init__(timeout=None)
        self.bridge = bridge
        self.guild_id = guild_id
        for button in PLAYBACK_CONTROL_BUTTONS:
            self.add_item(_PlaybackControlButton(button))


class _PlaybackControlButton(discord.ui.Button):
    def __init__(self, config: Dict[str, str]):
        style_name = config.get("style", "secondary")
        style = {
            "primary": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
        }.get(style_name, discord.ButtonStyle.secondary)
        super().__init__(
            label=config["label"],
            style=style,
            row=int(config.get("row", 0)),
            custom_id=f"djgoo:{config['intent']}",
        )
        self.intent = config["intent"]

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlaybackControlsView):
            return
        await view.bridge.handle_button_interaction(interaction, self.intent)


class DjGooAudioBridge:
    def __init__(self, *, bot, project_root: Path, send_payload: Callable[[Dict[str, Any]], Any]):
        self.bot = bot
        self.project_root = project_root
        self.playlists = DjGooPlaylists(project_root / "data" / "djgoo-playlists.json")
        self.stations = DjGooStations(project_root / "data" / "djgoo-stations.json")
        self.stations.clear_all_active()
        self._send_payload = send_payload
        self._recent_control_posts: Dict[int, tuple[str, float]] = {}

    async def handle(self, item: Dict[str, Any]) -> str:
        audio = self.bot.get_cog("Audio")
        if audio is None:
            await self._notice("Audio is not loaded yet.")
            return "Audio is not loaded"

        ctx = self._context()
        if ctx is None:
            await self._notice("Join a Discord voice channel once so DjGoo knows where to act.")
            return "No voice context"

        if item.get("type") == "followup":
            await self._notice("Choice follow-ups are ready for the search step. Say a full command for now.")
            return "Follow-up acknowledged"

        intent = str(item.get("intent", "unknown"))
        try:
            if intent == "start_radio":
                return await self._start_radio(audio, ctx, str(item.get("query", "")))
            if intent == "station_like_current":
                return await self._station_feedback(ctx, "liked", "Liked this for the active station.")
            if intent == "station_more_like_current":
                return await self._station_feedback(
                    ctx,
                    "more_like",
                    "Steering this station closer to this song.",
                )
            if intent == "station_less_like_current":
                return await self._station_feedback(
                    ctx,
                    "less_like",
                    "Steering this station away from this song.",
                )
            if intent == "station_ban_current":
                result = await self._station_feedback(
                    ctx,
                    "banned",
                    "This song will not play again on this station.",
                )
                await self._invoke(audio.command_skip, ctx)
                return result
            if intent == "station_status":
                return await self._station_status(ctx)
            if intent == "stop_radio":
                return await self._stop_radio(audio, ctx)
            if intent == "play":
                query = str(item.get("query", "")).strip()
                if not query:
                    await self._notice("I need a song name or URL.")
                    return "Missing query"
                if not await self._play_query_when_ready(audio, ctx, query):
                    await self._notice(
                        "DjGoo is still warming up the music engine. I did not start playback yet, "
                        "so try that command again in a few seconds if nothing starts."
                    )
                    return "Playback startup failed"
                await self._send_controls_for_player(ctx)
                return f"Playing {query}"
            if intent == "play_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=False)
            if intent == "shuffle_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=True)
            if intent in {"save_current_to_playlist", "save_last_to_playlist"}:
                return await self._save_track(ctx, str(item.get("playlist", "")), last=intent == "save_last_to_playlist")
            if intent == "skip":
                await self._mark_station_skip(ctx)
                await self._invoke(audio.command_skip, ctx)
                return "Skipped"
            if intent in {"pause", "resume"}:
                await self._pause_or_resume(audio, ctx, want_pause=intent == "pause")
                return intent.title()
            if intent == "stop":
                return await self._stop_playback(audio, ctx)
            if intent == "clear_queue":
                await self._invoke(audio.command_queue_clear, ctx)
                return "Queue cleared"
            if intent == "queue":
                await self._send_queue_summary(ctx)
                return "Queue shown"
            if intent == "now":
                await self._invoke(audio.command_now, ctx)
                return "Now playing"
            if intent == "disconnect":
                await self._invoke(audio.command_disconnect, ctx)
                return "Disconnected"
            if intent == "replay":
                await self._invoke(audio.command_prev, ctx)
                return "Replaying"
            if intent == "remove_current":
                await self._notice("Remove-current is queued for a later pass. Try `DjGoo skip` for now.")
                return "Remove current not wired"
            if intent == "volume":
                value = item.get("value")
                await self._invoke(audio.command_volume, ctx, vol=int(value))
                return f"Volume {value}"
            if intent == "volume_up":
                await self._relative_volume(audio, ctx, 10)
                return "Volume up"
            if intent == "volume_down":
                await self._relative_volume(audio, ctx, -10)
                return "Volume down"
            if intent == "cancel":
                await self._notice("Cancelled.")
                return "Cancelled"
            await self._notice(f"I heard `{item.get('raw', '')}`, but I do not know that command yet.")
            return "Unknown command"
        except Exception as exc:
            await self._notice(f"That command hit an error: `{type(exc).__name__}: {exc}`")
            raise

    def _context(self) -> Optional[DjGooAudioContext]:
        guild, author = self._active_voice_member()
        if guild is None or author is None:
            return None
        channel = self._best_text_channel(guild)
        if channel is None:
            return None
        return self._context_for(guild, author, channel)

    def _context_for(self, guild, author, channel) -> DjGooAudioContext:
        return DjGooAudioContext(
            bot=self.bot,
            guild=guild,
            author=author,
            channel=channel,
            send_payload=self._send_payload,
        )

    def _active_voice_member(self):
        for guild in self.bot.guilds:
            for channel in getattr(guild, "voice_channels", []):
                members = [member for member in channel.members if not member.bot]
                if members:
                    return guild, members[0]
        return None, None

    def _active_voice_channel(self, guild):
        for channel in getattr(guild, "voice_channels", []):
            members = [member for member in channel.members if not member.bot]
            if members:
                return channel
        return None

    def _can_send_to(self, guild, channel) -> bool:
        if channel is None:
            return False
        with contextlib.suppress(Exception):
            perms = channel.permissions_for(guild.me)
            return bool(perms.view_channel and perms.send_messages)
        return False

    def _configured_controls_channel(self, guild):
        secrets = load_secrets(self.project_root / "config" / "secrets.json")
        channel_id = str(secrets.get("voice", {}).get("controls_channel_id", "")).strip()
        if not channel_id:
            return None
        with contextlib.suppress(Exception):
            return guild.get_channel_or_thread(int(channel_id))
        return None

    def _best_text_channel(self, guild):
        configured_channel = self._configured_controls_channel(guild)
        if self._can_send_to(guild, configured_channel):
            return configured_channel
        active_voice_channel = self._active_voice_channel(guild)
        if self._can_send_to(guild, active_voice_channel):
            return active_voice_channel
        with contextlib.suppress(Exception):
            player = lavalink.get_player(guild.id)
            player_channel = getattr(player, "channel", None)
            if self._can_send_to(guild, player_channel):
                return player_channel
            notify_channel_id = player.fetch("notify_channel")
            if notify_channel_id:
                channel = guild.get_channel(int(notify_channel_id))
                if self._can_send_to(guild, channel):
                    return channel
        if self._can_send_to(guild, guild.system_channel):
            return guild.system_channel
        for channel in guild.text_channels:
            if self._can_send_to(guild, channel):
                return channel
        return None

    async def _invoke(self, command, ctx: DjGooAudioContext, *args, **kwargs):
        callback = getattr(command, "callback", None)
        if callback is None:
            return await command(ctx, *args, **kwargs)
        cog = self.bot.get_cog("Audio")
        return await callback(cog, ctx, *args, **kwargs)

    async def _play_playlist(self, audio, ctx, playlist_name: str, *, shuffle: bool) -> str:
        tracks = self.playlists.get_tracks(playlist_name)
        if not tracks:
            await self._notice(f"I could not find a DjGoo playlist named `{playlist_name}`.")
            return "Playlist missing"
        if shuffle:
            tracks = list(tracks)
            random.shuffle(tracks)
        for track in tracks:
            query = track.get("uri") or track.get("title")
            if query:
                await self._invoke(audio.command_play, ctx, query=str(query))
        await self._notice(f"Queued {len(tracks)} track(s) from `{playlist_name}`.")
        return f"Queued playlist {playlist_name}"

    async def _start_radio(self, audio, ctx, seed: str) -> str:
        seed = seed.strip()
        if not seed:
            await self._notice("Tell me what to seed the station with, like `DjGoo radio Sandstorm`.")
            return "Missing radio seed"
        if not await self._play_query_when_ready(audio, ctx, seed):
            await self._notice(
                "DjGoo is still warming up the music engine. I did not start the radio station yet, "
                "so it will not pretend music is playing."
            )
            return "Radio startup failed"
        station = self.stations.set_active(ctx.guild.id, seed)
        await self._notice(f"Started `{station['name']}`. I will keep this station's taste separate.")
        await self._send_controls_for_player(ctx)
        return f"Started {station['name']}"

    async def _play_query_when_ready(self, audio, ctx, query: str) -> bool:
        if not self._lavalink_node_ready(ctx.guild.id):
            await self._notice("DjGoo is warming up the music engine. I will start this as soon as it is ready.")
        if not await self._wait_for_lavalink_node(ctx.guild.id):
            log.warning("Lavalink was not ready after waiting for guild %s.", ctx.guild.id)
            return False
        await self._invoke(audio.command_play, ctx, query=query)
        return await self._wait_for_track_after_play(ctx.guild.id)

    async def _wait_for_lavalink_node(self, guild_id: int, *, timeout: float = 35.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._lavalink_node_ready(guild_id):
                return True
            await asyncio.sleep(1)
        return self._lavalink_node_ready(guild_id)

    def _lavalink_node_ready(self, guild_id: int) -> bool:
        try:
            lavalink.get_player(guild_id)
        except PlayerNotFound:
            return True
        except NodeNotFound:
            return False
        except Exception:
            log.debug("Could not check Lavalink readiness for guild %s.", guild_id, exc_info=True)
            return False
        return True

    async def _wait_for_track_after_play(self, guild_id: int, *, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._track_from_player_for_controls(guild_id) is not None:
                return True
            await asyncio.sleep(0.5)
        return self._track_from_player_for_controls(guild_id) is not None

    async def _station_feedback(self, ctx, bucket: str, message: str) -> str:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            await self._notice("No active radio station yet. Start one with `DjGoo radio <song>`.")
            return "No active station"
        track = self._selected_track(ctx.guild.id, last=False)
        if track is None:
            await self._notice("I could not read the current track.")
            return "No current track"
        self.stations.add_feedback(station["seed"], bucket, self._track_data(track))
        await self._notice(message)
        return message

    async def _station_status(self, ctx) -> str:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            await self._notice("No active radio station yet.")
            return "No active station"
        await self._notice(
            f"`{station['name']}`\n"
            f"Played: `{len(station['played'])}` | "
            f"Liked: `{len(station['liked'])}` | "
            f"Banned: `{len(station['banned'])}`"
        )
        return "Station status"

    async def _stop_radio(self, audio, ctx) -> str:
        station = self.stations.get_active(ctx.guild.id)
        self.stations.clear_active(ctx.guild.id)
        await self._invoke(audio.command_stop, ctx)
        if station is None:
            await self._notice("Radio mode is already off.")
            return "Radio already off"
        await self._notice(f"Stopped `{station['name']}`. DjGoo will not keep topping up that station.")
        return f"Stopped {station['name']}"

    async def _stop_playback(self, audio, ctx) -> str:
        station = self.stations.get_active(ctx.guild.id)
        self.stations.clear_active(ctx.guild.id)
        await self._invoke(audio.command_stop, ctx)
        if station is not None:
            await self._notice(f"Stopped playback and turned off `{station['name']}`.")
        return "Stopped"

    async def _save_track(self, ctx, playlist_name: str, *, last: bool) -> str:
        track = self._selected_track(ctx.guild.id, last=last)
        if track is None:
            await self._notice("There is no current or previous song to save yet.")
            return "No track"
        result = self.playlists.add_track(playlist_name, self._track_data(track))
        verb = "Added" if result.added else "Already had"
        await self._notice(
            f"{verb} `{track.title}` in `{result.playlist_name}` ({result.track_count} track(s))."
        )
        return f"{verb} track"

    def _selected_track(self, guild_id: int, *, last: bool):
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return None
        if last:
            previous = player.fetch("prev_song")
            if previous is not None:
                return previous
        return player.current

    def _track_data(self, track) -> Dict[str, str]:
        info = getattr(track, "info", {}) or {}
        return {
            "title": getattr(track, "title", "") or info.get("title", ""),
            "uri": getattr(track, "uri", "") or info.get("uri", ""),
        }

    async def _pause_or_resume(self, audio, ctx, *, want_pause: bool) -> None:
        try:
            player = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            await self._invoke(audio.command_pause, ctx)
            return
        if player.paused == want_pause:
            await self._notice("Already paused." if want_pause else "Already playing.")
            return
        await self._invoke(audio.command_pause, ctx)

    async def _toggle_pause(self, audio, ctx) -> str:
        try:
            player = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            await self._invoke(audio.command_pause, ctx)
            return "Toggled pause."
        was_paused = player.paused
        await self._invoke(audio.command_pause, ctx)
        return "Resumed." if was_paused else "Paused."

    async def _relative_volume(self, audio, ctx, delta: int) -> None:
        current = await audio.config.guild(ctx.guild).volume()
        await self._invoke(audio.command_volume, ctx, vol=max(0, min(150, int(current) + delta)))

    async def _mark_station_skip(self, ctx) -> None:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            return
        track = self._selected_track(ctx.guild.id, last=False)
        if track is not None:
            self.stations.add_feedback(station["seed"], "skipped", self._track_data(track))

    async def handle_station_track_start(self, guild, track) -> None:
        station = self.stations.get_active(guild.id)
        if station is None:
            return
        data = self._track_data(track)
        self.stations.mark_played(station["seed"], data)
        await self._send_payload(
            build_station_track_payload(
                station_name=station["name"],
                track=data,
                reason=self._station_reason(station),
            )
        )
        await self._top_up_station_queue(guild.id)

    async def handle_track_start(self, guild, track) -> None:
        await self._send_playback_controls(guild, track)
        await self.handle_station_track_start(guild, track)

    async def handle_track_enqueue(self, guild, track) -> None:
        log.info("DjGoo saw track enqueue in guild %s: %s", guild.id, getattr(track, "title", track))
        await self._send_playback_controls(guild, track)

    async def handle_red_track_enqueue_message(self, message) -> None:
        track = self._track_from_player_for_controls(message.guild.id)
        if track is None:
            log.warning("DjGoo saw Track Enqueued in #%s but could not find a current or queued track.", message.channel)
            return
        log.info("DjGoo saw visible Track Enqueued message in #%s.", message.channel)
        await self._send_playback_controls(message.guild, track, preferred_channel=message.channel)

    async def _send_controls_for_player(self, ctx: DjGooAudioContext) -> None:
        track = self._track_from_player_for_controls(ctx.guild.id)
        if track is None:
            log.warning("DjGoo found no current or queued track after play command in guild %s.", ctx.guild.id)
            return
        await self._send_playback_controls(ctx.guild, track, preferred_channel=ctx.channel)

    def _track_from_player_for_controls(self, guild_id: int):
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return None
        if player.queue:
            return player.queue[0]
        return player.current

    async def _send_playback_controls(self, guild, track, *, preferred_channel=None, force: bool = False) -> None:
        if not force and not self._should_post_playback_controls(guild.id, track):
            return
        channel = preferred_channel or self._best_text_channel(guild)
        if channel is None:
            log.warning("DjGoo could not find a text channel for playback controls in guild %s.", guild.id)
            return
        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages:
            log.warning("DjGoo cannot send playback controls in #%s: missing send_messages.", channel)
            return
        data = self._track_data(track)
        station = self.stations.get_active(guild.id)
        embed = discord.Embed.from_dict(
            build_playback_control_embed(
                data,
                station_name=station["name"] if station else None,
            )
        )
        view = PlaybackControlsView(self, guild.id)
        try:
            await channel.send(embed=embed, view=view)
            log.info(
                "DjGoo posted playback controls in #%s for %s.",
                channel,
                data.get("title", "unknown track"),
            )
        except (discord.HTTPException, discord.Forbidden):
            log.exception("DjGoo failed to send playback controls in #%s.", channel)

    def _should_post_playback_controls(self, guild_id: int, track) -> bool:
        key = self._track_key(track)
        now = time.monotonic()
        previous = self._recent_control_posts.get(guild_id)
        if previous is not None:
            previous_key, previous_time = previous
            if previous_key == key and now - previous_time < 30:
                return False
        self._recent_control_posts[guild_id] = (key, now)
        return True

    def _track_key(self, track) -> str:
        identifier = getattr(track, "track_identifier", "")
        if identifier:
            return str(identifier)
        data = self._track_data(track)
        return data.get("uri") or data.get("title") or repr(track)

    async def handle_button_interaction(self, interaction: discord.Interaction, intent: str) -> None:
        if interaction.guild is None or interaction.channel is None or interaction.user is None:
            return
        await interaction.response.defer(ephemeral=True)
        ctx = self._context_for(interaction.guild, interaction.user, interaction.channel)
        audio = self.bot.get_cog("Audio")
        if audio is None:
            await interaction.followup.send("Audio is not loaded yet.", ephemeral=True)
            return
        item = {"type": "command", "intent": intent, "raw": f"button:{intent}", "source": "button"}
        try:
            if intent == "skip":
                await self._mark_station_skip(ctx)
                await self._invoke(audio.command_skip, ctx)
                message = "Skipped."
            elif intent == "toggle_pause":
                message = await self._toggle_pause(audio, ctx)
            elif intent == "stop":
                message = await self._stop_playback(audio, ctx)
            elif intent == "replay":
                await self._invoke(audio.command_prev, ctx)
                message = "Replaying."
            elif intent == "queue":
                message = self._queue_summary_text(ctx.guild.id)
            elif intent == "volume_up":
                await self._relative_volume(audio, ctx, 10)
                message = "Volume up."
            elif intent == "volume_down":
                await self._relative_volume(audio, ctx, -10)
                message = "Volume down."
            elif intent == "station_like_current":
                message = await self._station_feedback(ctx, "liked", "Liked this for the active station.")
            elif intent == "station_more_like_current":
                message = await self._station_feedback(
                    ctx,
                    "more_like",
                    "Steering this station closer to this song.",
                )
            elif intent == "station_less_like_current":
                message = await self._station_feedback(
                    ctx,
                    "less_like",
                    "Steering this station away from this song.",
                )
            elif intent == "station_ban_current":
                message = await self._station_feedback(
                    ctx,
                    "banned",
                    "This song will not play again on this station.",
                )
                await self._invoke(audio.command_skip, ctx)
            else:
                message = await self.handle(item)
            await interaction.followup.send(message[:2000], ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"DjGoo hit an error: {type(exc).__name__}: {exc}", ephemeral=True)
            raise

    def _station_reason(self, station: Dict[str, Any]) -> str:
        if station.get("liked"):
            return "Because you liked tracks on this station"
        if station.get("more_like"):
            return "Steered by more-like-this"
        return "Fresh similar pick"

    async def _top_up_station_queue(self, guild_id: int) -> None:
        station = self.stations.get_active(guild_id)
        if station is None:
            return
        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            return
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        if len(player.queue) >= 2:
            return
        seeds = [station["seed"]]
        if station.get("liked"):
            seeds.append(station["liked"][-1]["title"])
        if station.get("more_like"):
            seeds.append(station["more_like"][-1]["title"])
        query = f"{random.choice(seeds)} similar music"
        await self._invoke(audio.command_play, ctx, query=query)

    async def _send_queue_summary(self, ctx) -> None:
        await self._notice(self._queue_summary_text(ctx.guild.id))

    def _queue_summary_text(self, guild_id: int) -> str:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return "There is nothing in the queue."
        lines = []
        if player.current:
            lines.append(f"Now: `{player.current.title}`")
        for index, track in enumerate(player.queue[:5], start=1):
            lines.append(f"{index}. `{track.title}`")
        return "\n".join(lines) if lines else "There is nothing in the queue."

    async def _notice(self, description: str) -> None:
        await self._send_payload(
            {
                "username": "DjGoo",
                "embeds": [
                    {
                        "title": "DjGoo",
                        "description": description[:4096],
                        "color": 0x2F80ED,
                    }
                ],
            }
        )
