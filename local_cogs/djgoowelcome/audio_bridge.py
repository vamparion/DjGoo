from __future__ import annotations

import contextlib
import asyncio
from contextvars import ContextVar
import json
import logging
import os
import random
import re
import time
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import discord
import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.djgoo_playlists import DjGooPlaylists
from voice.nuclear_resolver import NuclearResolver
from voice.djgoo_stations import DjGooStations, track_key
from voice.operational_log import log_event
from voice.duplicate_policy import filter_automatic_duplicates

from .helpers import (
    PLAYBACK_CONTROL_BUTTONS,
    build_playback_control_embed,
    build_station_track_payload,
    load_secrets,
)


log = logging.getLogger("red.djgoowelcome.audio_bridge")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COMMAND_CONTEXT: ContextVar[Optional["DjGooAudioContext"]] = ContextVar(
    "djgoo_audio_command_context",
    default=None,
)

MAX_TRACK_SECONDS = 10 * 60
MAX_PLAY_EXPANSION_TRACKS = 25
MAX_PLAYLIST_EXPANSION_TRACKS = 500

RADIO_REJECT_TITLE_PHRASES = (
    "instrumental",
    "karaoke",
    "cover",
    "reaction",
    "reacts",
    "interview",
    "lesson",
    "tutorial",
    "how to",
    "similarities",
    "similarity",
    "documentary",
    "behind the scenes",
    "making of",
    "shorts",
    "#shorts",
    "clip",
    "compilation",
    "collection",
    "playlist",
    "full album",
    "greatest hits",
    "mix",
    " dj set",
    "hour of",
    "hours of",
    "live at",
    "live from",
    "live in",
)

RADIO_SEARCH_EXCLUSIONS = (
    "instrumental",
    "karaoke",
    "cover",
    "reaction",
    "similarities",
    "interview",
    "lesson",
    "tutorial",
    "clip",
    "shorts",
    "playlist",
    "mix",
    "full album",
    "live",
)

VOICE_NON_MUSIC_QUERY_RE = re.compile(
    r"\b(?:settings?|turn\s+off|turn\s+on|tutorial|how\s+to|updated\s+\d{4})\b",
    re.IGNORECASE,
)


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


class _VoiceAuthorProxy:
    def __init__(self, member, voice_channel):
        self._member = member
        self.voice = type("VoiceState", (), {"channel": voice_channel})()

    def __getattr__(self, name):
        return getattr(self._member, name)


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
        self.suppress_sends = False

    def typing(self):
        return _NoopTyping()

    async def send(self, content=None, **kwargs):
        if self.suppress_sends:
            return _FakeMessage()
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
        log_event(
            "discord.button.clicked",
            guild_id=getattr(interaction.guild, "id", None),
            channel_id=getattr(interaction.channel, "id", None),
            user_id=getattr(interaction.user, "id", None),
            intent=self.intent,
        )
        await view.bridge.handle_button_interaction(interaction, self.intent)


class DjGooAudioBridge:
    def __init__(self, *, bot, project_root: Path, send_payload: Callable[[Dict[str, Any]], Any]):
        self.bot = bot
        self.project_root = project_root
        self.playlists = DjGooPlaylists(project_root / "data" / "djgoo-playlists.json")
        self.stations = DjGooStations(project_root / "data" / "djgoo-stations.json")
        self.playback_state_path = project_root / "data" / "djgoo-playback-state.json"
        if not self._should_resume_playback():
            self.stations.clear_all_active()
            self._clear_playback_state()
        self.nuclear = NuclearResolver()
        self._send_payload = send_payload
        self._recent_control_posts: Dict[int, tuple[str, float]] = {}
        self._ytmusic = None
        log_event("bridge.initialized", resume_playback=self._should_resume_playback())

    def _should_resume_active_radio(self) -> bool:
        return self._should_resume_playback()

    def _should_resume_playback(self) -> bool:
        return os.environ.get("DJGOO_RESUME_PLAYBACK", "").strip() == "1" or os.environ.get("DJGOO_RESUME_ACTIVE_RADIO", "").strip() == "1"

    def _playback_state_path(self) -> Path:
        configured = getattr(self, "playback_state_path", None)
        if isinstance(configured, Path):
            return configured
        project_root = getattr(self, "project_root", PROJECT_ROOT)
        return Path(project_root) / "data" / "djgoo-playback-state.json"

    async def handle(self, item: Dict[str, Any]) -> str:
        log_event(
            "bridge.command.start",
            type=item.get("type"),
            source=item.get("source"),
            intent=item.get("intent"),
            action=item.get("action"),
            query=item.get("query"),
            playlist=item.get("playlist"),
            raw=item.get("raw"),
        )
        audio = self.bot.get_cog("Audio")
        if audio is None:
            await self._notice("Audio is not loaded yet.")
            log_event("bridge.command.no_audio", item=item)
            return "Audio is not loaded"

        ctx = self._context()
        if ctx is None:
            await self._notice("Join a Discord voice channel once so DjGoo knows where to act.")
            log_event("bridge.command.no_context", item=item, guild_count=len(self.bot.guilds))
            return "No voice context"

        if item.get("type") == "followup":
            await self._notice("Choice follow-ups are ready for the search step. Say a full command for now.")
            log_event("bridge.followup.acknowledged", item=item)
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
                resolved_queries = await self._resolve_play_queries(query, source=str(item.get("source", "")))
                if not resolved_queries:
                    await self._notice("I could not find a clean playable version of that.")
                    return "No clean play query"
                if not await self._play_queries_when_ready(audio, ctx, resolved_queries):
                    await self._notice(
                        "DjGoo is still warming up the music engine. I did not start playback yet, "
                        "so try that command again in a few seconds if nothing starts."
                    )
                    return "Playback startup failed"
                return f"Playing {resolved_queries[0]}"
            if intent == "play_album":
                return await self._play_album(audio, ctx, str(item.get("query", "")))
            if intent == "play_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=False)
            if intent == "shuffle_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=True)
            if intent in {"save_current_to_playlist", "save_last_to_playlist"}:
                return await self._save_track(ctx, str(item.get("playlist", "")), last=intent == "save_last_to_playlist")
            if intent == "skip":
                if await self._skip_playback(audio, ctx):
                    return "Skipped"
                return "Skip failed: player did not advance"
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
                if await self._skip_playback(audio, ctx):
                    return "Removed current track"
                return "Remove current failed: player did not advance"
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
            log_event(
                "bridge.command.exception",
                intent=item.get("intent"),
                error=type(exc).__name__,
                detail=str(exc),
            )
            raise

    async def handle_from_discord_context(self, item: Dict[str, Any], ctx, voice_channel=None) -> str:
        author = ctx.author
        author_voice_channel = getattr(getattr(author, "voice", None), "channel", None)
        if author_voice_channel is None and voice_channel is not None:
            author = _VoiceAuthorProxy(author, voice_channel)
        command_context = self._context_for(ctx.guild, author, ctx.channel)
        token = _COMMAND_CONTEXT.set(command_context)
        try:
            return await self.handle(item)
        finally:
            _COMMAND_CONTEXT.reset(token)

    def _context(self) -> Optional[DjGooAudioContext]:
        command_context = _COMMAND_CONTEXT.get()
        if command_context is not None:
            log_event(
                "bridge.context.command.selected",
                guild_id=getattr(command_context.guild, "id", None),
                member_id=getattr(command_context.author, "id", None),
                voice_channel_id=getattr(
                    getattr(getattr(command_context.author, "voice", None), "channel", None),
                    "id",
                    None,
                ),
            )
            return command_context
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
                    log_event(
                        "bridge.context.voice_member.selected",
                        guild_id=guild.id,
                        voice_channel_id=getattr(channel, "id", None),
                        member_id=getattr(members[0], "id", None),
                    )
                    return guild, members[0]
        log_event("bridge.context.no_voice_members", guild_count=len(self.bot.guilds))
        return None, None

    def _active_voice_channel(self, guild):
        for channel in getattr(guild, "voice_channels", []):
            members = [member for member in channel.members if not member.bot]
            if members:
                return channel
        return None

    def _active_voice_member_for_guild(self, guild):
        for channel in getattr(guild, "voice_channels", []):
            members = [member for member in channel.members if not member.bot]
            if members:
                return members[0]
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
            log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=configured_channel.id, reason="configured")
            return configured_channel
        active_voice_channel = self._active_voice_channel(guild)
        if self._can_send_to(guild, active_voice_channel):
            log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=active_voice_channel.id, reason="active_voice")
            return active_voice_channel
        with contextlib.suppress(Exception):
            player = lavalink.get_player(guild.id)
            player_channel = getattr(player, "channel", None)
            if self._can_send_to(guild, player_channel):
                log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=player_channel.id, reason="player_channel")
                return player_channel
            notify_channel_id = player.fetch("notify_channel")
            if notify_channel_id:
                channel = guild.get_channel(int(notify_channel_id))
                if self._can_send_to(guild, channel):
                    log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=channel.id, reason="notify_channel")
                    return channel
        if self._can_send_to(guild, guild.system_channel):
            log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=guild.system_channel.id, reason="system_channel")
            return guild.system_channel
        for channel in guild.text_channels:
            if self._can_send_to(guild, channel):
                log_event("bridge.context.text_channel.selected", guild_id=guild.id, channel_id=channel.id, reason="first_text_channel")
                return channel
        log_event("bridge.context.no_text_channel", guild_id=guild.id)
        return None

    async def _invoke(self, command, ctx: DjGooAudioContext, *args, **kwargs):
        log_event(
            "redbot.command.invoke",
            guild_id=getattr(ctx.guild, "id", None),
            channel_id=getattr(ctx.channel, "id", None),
            command=getattr(command, "qualified_name", repr(command)),
            args=[str(arg) for arg in args],
            kwargs=kwargs,
        )
        callback = getattr(command, "callback", None)
        if callback is None:
            return await command(ctx, *args, **kwargs)
        cog = self.bot.get_cog("Audio")
        return await callback(cog, ctx, *args, **kwargs)

    async def _invoke_silently(self, command, ctx: DjGooAudioContext, *args, **kwargs):
        previous_suppress_sends = getattr(ctx, "suppress_sends", False)
        ctx.suppress_sends = True
        try:
            return await self._invoke(command, ctx, *args, **kwargs)
        finally:
            ctx.suppress_sends = previous_suppress_sends

    async def resume_active_radio_stations(self) -> None:
        if not self._should_resume_active_radio():
            log_event("radio.resume.skipped", reason="resume_flag_not_set")
            return
        audio = self.bot.get_cog("Audio")
        if audio is None:
            return
        active_guild_ids = set(self.stations.active_guild_ids())
        for guild in self.bot.guilds:
            if int(guild.id) not in active_guild_ids:
                continue
            station = self.stations.get_active(guild.id)
            if station is None or self._player_has_music(guild.id):
                log_event("radio.resume.skipped_guild", guild_id=guild.id, reason="no_station_or_music_already_present")
                continue
            author = self._active_voice_member_for_guild(guild)
            channel = self._best_text_channel(guild)
            if author is None or channel is None:
                log_event("radio.resume.skipped_guild", guild_id=guild.id, reason="missing_author_or_channel")
                continue
            ctx = self._context_for(guild, author, channel)
            query = await self._radio_fallback_query(station["seed"])
            log_event("radio.resume.playing", guild_id=guild.id, station=station["name"], seed=station["seed"], query=query)
            await self._play_query_when_ready(audio, ctx, query)

    async def resume_saved_playback(self) -> None:
        if not self._should_resume_playback():
            log_event("playback.resume.skipped", reason="resume_flag_not_set")
            return
        audio = self.bot.get_cog("Audio")
        if audio is None:
            log_event("playback.resume.skipped", reason="missing_audio")
            return
        state = self._read_playback_state()
        if not state:
            log_event("playback.resume.skipped", reason="missing_state")
            await self.resume_active_radio_stations()
            return
        resumed_any = False
        for guild in self.bot.guilds:
            guild_state = state.get(str(guild.id))
            if not isinstance(guild_state, dict):
                continue
            if await self._wait_for_existing_player_music(guild.id):
                log_event("playback.resume.skipped_guild", guild_id=guild.id, reason="music_already_present")
                continue
            author = self._active_voice_member_for_guild(guild)
            channel = self._best_text_channel(guild)
            if author is None or channel is None:
                log_event("playback.resume.skipped_guild", guild_id=guild.id, reason="missing_author_or_channel")
                continue
            ctx = self._context_for(guild, author, channel)
            self._restore_saved_provenance(guild.id, guild_state)
            tracks = self._state_tracks_to_queries(guild_state)
            if tracks:
                log_event(
                    "playback.resume.playing",
                    guild_id=guild.id,
                    query_count=len(tracks),
                    mode=guild_state.get("mode"),
                    current=(guild_state.get("current") or {}).get("title"),
                )
                if await self._restore_playback_queries(
                    audio,
                    ctx,
                    tracks,
                    position_seconds=int(guild_state.get("position_seconds") or 0),
                    volume=(
                        int(guild_state.get("volume"))
                        if guild_state.get("volume") is not None
                        else None
                    ),
                    paused=bool(guild_state.get("paused")),
                ):
                    resumed_any = True
                    station = self.stations.get_active(guild.id)
                    if station is not None:
                        await self._top_up_station_queue(guild.id)
                continue
            station = self.stations.get_active(guild.id)
            if station is not None:
                query = await self._radio_fallback_query(station["seed"])
                log_event("playback.resume.radio_fallback", guild_id=guild.id, station=station["name"], seed=station["seed"], query=query)
                if await self._play_query_when_ready(audio, ctx, query):
                    resumed_any = True
        if not resumed_any:
            await self.resume_active_radio_stations()

    async def _wait_for_existing_player_music(
        self,
        guild_id: int,
        *,
        timeout_seconds: float = 4.0,
    ) -> bool:
        """Give Red's Audio cog time to reconstruct a resumed player."""

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            if self._player_has_music(guild_id):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.25)

    def _read_playback_state(self) -> Dict[str, Any]:
        path = self._playback_state_path()
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            log_event("playback.state.read_failed", path=str(path))
            return {}
        guilds = data.get("guilds", {}) if isinstance(data, dict) else {}
        return guilds if isinstance(guilds, dict) else {}

    def _write_playback_state(self, guild_id: int, state: Dict[str, Any]) -> None:
        all_state = self._read_playback_state()
        all_state[str(guild_id)] = state
        path = self._playback_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as fp:
            json.dump({"guilds": all_state}, fp, indent=2, ensure_ascii=True)
            fp.write("\n")
        temp_path.replace(path)
        log_event("playback.state.saved", guild_id=guild_id, mode=state.get("mode"), queue_count=len(state.get("queue", [])))

    def _clear_playback_state(self, guild_id: Optional[int] = None) -> None:
        path = self._playback_state_path()
        if guild_id is None:
            path.unlink(missing_ok=True)
            log_event("playback.state.cleared", scope="all")
            return
        all_state = self._read_playback_state()
        all_state.pop(str(guild_id), None)
        if not all_state:
            path.unlink(missing_ok=True)
        else:
            temp_path = path.with_suffix(".json.tmp")
            with temp_path.open("w", encoding="utf-8") as fp:
                json.dump({"guilds": all_state}, fp, indent=2, ensure_ascii=True)
                fp.write("\n")
            temp_path.replace(path)
        log_event("playback.state.cleared", scope="guild", guild_id=guild_id)

    def _persist_player_state(self, guild_id: int, *, reason: str) -> None:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            log_event("playback.state.save_skipped", guild_id=guild_id, reason="no_player")
            return
        current = self._state_track_snapshot(guild_id, player.current) if player.current else {}
        queue = [
            self._state_track_snapshot(guild_id, track)
            for track in list(getattr(player, "queue", []) or [])[:50]
        ]
        if not current and not queue:
            log_event("playback.state.save_skipped", guild_id=guild_id, reason="empty_player")
            return
        station = self.stations.get_active(guild_id)
        state = {
            "mode": "radio" if station is not None else "playback",
            "saved_at": time.time(),
            "reason": reason,
            "current": current,
            "queue": queue,
            "position_seconds": self._player_position_seconds(player, current),
            "volume": int(getattr(player, "volume", 0) or 0),
            "paused": bool(getattr(player, "paused", False)),
            "station": {
                "name": station.get("name", ""),
                "seed": station.get("seed", ""),
            }
            if station is not None
            else None,
        }
        self._write_playback_state(guild_id, state)

    def _player_position_seconds(self, player: Any, current: Dict[str, Any]) -> int:
        position = int(getattr(player, "position", 0) or 0)
        duration = int(current.get("duration_seconds") or 0)
        if position > max(10_000, duration * 10):
            position //= 1000
        return max(0, position)

    def _state_track_snapshot(self, guild_id: int, track: Any) -> Dict[str, Any]:
        data: Dict[str, Any] = dict(self._track_data(track))
        data["track_key"] = self._track_key(track)
        entry_id = ""
        stable_id = getattr(self, "_stable_track_id", None)
        if callable(stable_id):
            entry_id = str(stable_id(track) or "")
        requests = getattr(self, "request_ledger", None)
        origins = getattr(self, "queue_origins", None)
        metadata: Dict[str, Any] = {}
        if requests is not None:
            metadata = next(
                (
                    entry
                    for entry in requests.entries(guild_id)
                    if entry_id and str(entry.get("entry_id") or "") == entry_id
                ),
                {},
            )
        if not metadata and origins is not None:
            metadata = next(
                (
                    entry
                    for entry in origins.entries(guild_id)
                    if entry_id and str(entry.get("entry_id") or "") == entry_id
                ),
                {},
            )
        data.update(
            {
                "entry_id": entry_id,
                "source": str(metadata.get("source") or "recovery"),
                "lane": str(metadata.get("lane") or "program"),
                "requester_id": int(metadata.get("requester_id") or 0),
                "requester_name": str(metadata.get("requester_name") or ""),
                "request_timing": str(metadata.get("timing") or ""),
                "label": str(metadata.get("label") or ""),
                "insertion_reason": str(metadata.get("insertion_reason") or "Saved playback entry"),
            }
        )
        return data

    def _restore_saved_provenance(self, guild_id: int, guild_state: Dict[str, Any]) -> None:
        tracks = [guild_state.get("current"), *list(guild_state.get("queue") or [])]
        requests = []
        origins = []
        now = time.time()
        for track in tracks:
            if not isinstance(track, dict) or not str(track.get("track_key") or ""):
                continue
            entry = {
                "track_key": str(track.get("track_key") or ""),
                "title": str(track.get("title") or ""),
                "timing": str(track.get("request_timing") or "next"),
                "requester_id": int(track.get("requester_id") or 0),
                "requester_name": str(track.get("requester_name") or ""),
                "entry_id": str(track.get("entry_id") or ""),
                "lane": str(track.get("lane") or "program"),
                "insertion_reason": str(track.get("insertion_reason") or "Restart recovery"),
                "source": str(track.get("source") or "recovery"),
                "created_at": now,
            }
            if entry["lane"] == "request":
                requests.append(entry)
            else:
                origins.append({**entry, "label": str(track.get("label") or "")})
        request_ledger = getattr(self, "request_ledger", None)
        if request_ledger is not None:
            request_ledger.replace_entries(guild_id, requests)
        origin_ledger = getattr(self, "queue_origins", None)
        if origin_ledger is not None:
            origin_ledger.replace_entries(guild_id, origins)

    def _state_tracks_to_queries(self, guild_state: Dict[str, Any]) -> List[str]:
        tracks = []
        current = guild_state.get("current")
        if isinstance(current, dict):
            tracks.append(current)
        tracks.extend(track for track in guild_state.get("queue", []) or [] if isinstance(track, dict))
        filtered, skipped = filter_automatic_duplicates(tracks)
        if skipped:
            log_event("playback.resume.duplicates_filtered", count=skipped)
        queries = []
        for track in filtered:
            query = str(track.get("uri") or track.get("title") or "").strip()
            if not query:
                continue
            queries.append(query)
        return queries[:50]

    def _player_has_music(self, guild_id: int) -> bool:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return False
        return bool(player.current or player.queue)

    async def _play_playlist(self, audio, ctx, playlist_name: str, *, shuffle: bool) -> str:
        tracks = self.playlists.get_tracks(playlist_name)
        if not tracks:
            await self._notice(f"I could not find a DjGoo playlist named `{playlist_name}`.")
            return "Playlist missing"
        if shuffle:
            tracks = list(tracks)
            random.shuffle(tracks)

        guild_id = int(ctx.guild.id)
        existing = self._player_track_identities(guild_id)
        queued_tracks = []
        skipped = 0
        for track in tracks:
            identity = self._track_identity(track)
            if identity and identity in existing:
                skipped += 1
                continue
            queued_tracks.append(track)
            if identity:
                existing.add(identity)

        for track in queued_tracks:
            query = track.get("uri") or track.get("title")
            if query:
                previous_ids = self._player_object_ids(guild_id)
                await self._invoke(audio.command_play, ctx, query=str(query))
                self._remember_new_queue_origin(
                    guild_id,
                    previous_ids,
                    source="playlist",
                    label=playlist_name,
                )
        if not queued_tracks:
            message = f"All {skipped} track(s) from `{playlist_name}` are already playing or queued."
        else:
            message = f"Queued {len(queued_tracks)} track(s) from `{playlist_name}`."
            if skipped:
                message += f" Skipped {skipped} already playing or queued."
        await self._notice(message)
        return message

    def _player_track_identities(self, guild_id: int) -> set[str]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return set()
        tracks = [getattr(player, "current", None), *list(getattr(player, "queue", []))]
        return {
            identity
            for track in tracks
            if track is not None
            if (identity := self._track_identity(track))
        }

    def _player_object_ids(self, guild_id: int) -> set[int]:
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return set()
        return {id(track) for track in list(getattr(player, "queue", []))}

    def _remember_new_queue_origin(
        self,
        guild_id: int,
        previous_ids: set[int],
        *,
        source: str,
        label: str = "",
    ) -> None:
        ledger = getattr(self, "queue_origins", None)
        if ledger is None:
            return
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        added = [track for track in list(player.queue) if id(track) not in previous_ids]
        if added:
            selected = added[-1]
            stable_id = getattr(self, "_stable_track_id", lambda _track: "")(selected)
            lane = "radio" if source == "radio" else "program"
            ledger.add(
                guild_id,
                track_key=self._track_key(selected),
                source=source,
                label=label,
                entry_id=stable_id,
                lane=lane,
                insertion_reason=(
                    f"Saved playlist: {label}" if source == "playlist" and label else source
                ),
            )

    def _track_identity(self, track: Any) -> str:
        data = dict(track) if isinstance(track, dict) else self._track_data(track)
        uri = str(data.get("uri") or "").strip()
        video_id = self._youtube_video_id(uri)
        if video_id:
            return f"youtube:{video_id.lower()}"
        if uri:
            return f"uri:{uri.lower()}"
        title = re.sub(r"\s+", " ", str(data.get("title") or "").strip().lower())
        artist = re.sub(r"\s+", " ", str(data.get("artist") or "").strip().lower())
        return f"title:{title}|{artist}" if title else ""

    async def _resolve_play_query(self, query: str) -> str:
        resolved = await self._resolve_play_queries(query)
        return resolved[0] if resolved else query

    async def _resolve_play_queries(self, query: str, *, source: str = "") -> List[str]:
        original_query = query
        query = self._repair_voice_play_query(query) if source == "voice" else query
        if query != original_query:
            log_event("play.voice_query.repaired", original_query=original_query, repaired_query=query)
        cleaned_youtube = await self._resolve_youtube_play_query(query)
        if cleaned_youtube is not None:
            log_event("play.resolve.done", query=query, resolved_query=cleaned_youtube, used_youtube_guard=True)
            return cleaned_youtube
        resolved = await asyncio.to_thread(self.nuclear.resolve_track_query, query)
        if resolved:
            log_event("play.resolve.done", query=query, resolved_query=resolved, used_nuclear=True)
            return [resolved]
        ytmusic_resolved = await asyncio.to_thread(self._ytmusic_song_search_query, query)
        if ytmusic_resolved:
            log_event("play.resolve.done", query=query, resolved_query=ytmusic_resolved, used_ytmusic=True)
            return [ytmusic_resolved]
        if source == "voice" and VOICE_NON_MUSIC_QUERY_RE.search(query):
            log_event("play.resolve.blocked_raw_voice_query", query=query, original_query=original_query)
            return []
        log_event("play.resolve.done", query=query, resolved_query=query, used_nuclear=False, used_ytmusic=False)
        return [query]

    def _repair_voice_play_query(self, query: str) -> str:
        repaired = re.sub(r"\blindy\s+stirling\b", "Lindsey Stirling", query, flags=re.IGNORECASE)
        repaired = re.sub(r"\blindsey\s+sterling\b", "Lindsey Stirling", repaired, flags=re.IGNORECASE)
        if re.search(r"\bshadow[s]?\b", repaired, re.IGNORECASE) and re.search(r"\bdensity\s+turn\s+off\b", repaired, re.IGNORECASE):
            return "Shadows Lindsey Stirling"
        return re.sub(r"\s+", " ", repaired).strip()

    async def _resolve_radio_seed_query(self, seed: str) -> str:
        search_query = self._radio_seed_search_query(seed)
        resolved = await asyncio.to_thread(self._ytmusic_song_search_query, search_query, True)
        if resolved:
            log_event("radio.seed.resolve.done", seed=seed, resolved_query=resolved, used_ytmusic=True)
            return resolved
        return await self._radio_fallback_query(seed)

    async def _radio_fallback_query(self, seed: str) -> str:
        resolver = getattr(self, "nuclear", None)
        search_query = self._radio_seed_search_query(seed)
        resolved = await asyncio.to_thread(resolver.resolve_track_query, search_query) if resolver is not None else None
        fallback = self._radio_search_query(seed)
        log_event(
            "radio.seed.resolve.done",
            seed=seed,
            nuclear_search_query=search_query,
            resolved_query=resolved or fallback,
            used_nuclear=bool(resolved),
        )
        return resolved or fallback

    def _radio_seed_search_query(self, seed: str) -> str:
        normalized = re.sub(r"\s+", " ", seed.strip().lower())
        aliases = {
            "80s": "80s hits",
            "80's": "80s hits",
            "90s": "90s hits",
            "90's": "90s hits",
            "rock": "rock hits",
            "edm": "edm hits",
            "country": "country hits",
            "rap": "rap hits",
            "r&b": "r&b hits",
            "white girl music": "2000s pop hits",
        }
        if normalized in aliases:
            return aliases[normalized]
        if re.search(r"\b(hit|hits|music|songs|radio)\b", normalized, re.IGNORECASE):
            return seed.strip()
        return seed.strip()

    async def _play_album(self, audio, ctx, query: str) -> str:
        query = query.strip()
        if not query:
            await self._notice("Tell me which album to play.")
            return "Missing album query"
        tracks = await asyncio.to_thread(self.nuclear.resolve_album_queries, query)
        if not tracks:
            await self._notice(f"I could not find album tracks for `{query}`.")
            return "Album missing"
        for track_query in tracks:
            await self._invoke(audio.command_play, ctx, query=track_query)
        await self._notice(f"Queued {len(tracks)} track(s) from `{query}`.")
        return f"Queued album {query}"

    async def _start_radio(self, audio, ctx, seed: str) -> str:
        seed = seed.strip()
        if not seed:
            await self._notice("Tell me what to seed the station with, like `DjGoo radio Sandstorm`.")
            return "Missing radio seed"
        station_seed = seed
        station_mode = "balanced"
        split_mode = getattr(self, "_split_radio_mode", None)
        if callable(split_mode):
            station_mode, station_seed = split_mode(seed)
        self._lifecycle_transition(
            ctx.guild.id,
            "loading",
            reason="Resolving radio seed",
        )
        play_query = await self._resolve_radio_seed_query(seed)
        station = self.stations.set_active(ctx.guild.id, station_seed)
        set_mode = getattr(self.stations, "set_mode", None)
        if callable(set_mode):
            station = set_mode(station_seed, station_mode)
        seed_video_id = self._youtube_video_id(play_query)
        if seed_video_id:
            station = self.stations.set_seed_track(
                station_seed,
                {
                    "title": station_seed,
                    "uri": f"https://www.youtube.com/watch?v={seed_video_id}",
                },
            )
        log_event("radio.start.play_seed", guild_id=ctx.guild.id, seed=seed, play_query=play_query)
        if not await self._play_query_when_ready(audio, ctx, play_query):
            self.stations.clear_active(ctx.guild.id)
            await self._notice(
                "DjGoo is still warming up the music engine. I did not start the radio station yet, "
                "so it will not pretend music is playing."
            )
            return "Radio startup failed"
        station = self.stations.get_active(ctx.guild.id) or station
        selected = self._selected_track(ctx.guild.id, last=False)
        if selected is not None:
            data = self._track_data(selected)
            key = self._track_key(selected)
            self._lifecycle_transition(
                ctx.guild.id,
                "queued",
                reason="Player confirmed radio seed",
                track=data,
                track_key=key,
            )
            self._lifecycle_transition(
                ctx.guild.id,
                "playing",
                reason="Radio seed is playing",
                track=data,
                track_key=key,
            )
        log_event("radio.start.active", guild_id=ctx.guild.id, station=station["name"], seed=seed)
        await self._notice(f"Started `{station['name']}`. I will keep this station's taste separate.")
        return f"Started {station['name']}"

    async def _play_query_when_ready(self, audio, ctx, query: str) -> bool:
        return await self._play_queries_when_ready(audio, ctx, [query])

    async def _restore_playback_queries(
        self,
        audio: Any,
        ctx: Any,
        queries: List[str],
        *,
        position_seconds: int = 0,
        volume: int | None = None,
        paused: bool = False,
    ) -> bool:
        """Start the saved current track before appending its saved queue."""

        queries = [query for query in queries if str(query).strip()]
        if not queries:
            return False
        if not await self._play_query_when_ready(audio, ctx, queries[0]):
            return False
        guild = getattr(ctx, "guild", None)
        player = None
        if guild is not None:
            try:
                player = lavalink.get_player(guild.id)
            except (NodeNotFound, PlayerNotFound):
                player = None
        if player is not None and position_seconds > 0:
            result = player.seek(max(0, int(position_seconds)) * 1000)
            if hasattr(result, "__await__"):
                await result
        if volume is not None:
            await self._invoke_silently(
                audio.command_volume,
                ctx,
                vol=max(0, min(150, int(volume))),
            )
        if paused:
            await self._invoke_silently(audio.command_pause, ctx)
        for query in queries[1:]:
            await self._invoke_silently(audio.command_play, ctx, query=query)
        return True

    async def _play_queries_when_ready(self, audio, ctx, queries: List[str]) -> bool:
        queries = [query for query in queries if str(query).strip()]
        if not queries:
            return False
        if not self._lavalink_node_ready(ctx.guild.id):
            await self._notice("DjGoo is warming up the music engine. I will start this as soon as it is ready.")
            log_event("play.lavalink.waiting", guild_id=ctx.guild.id, query=queries[0], query_count=len(queries))
        if not await self._wait_for_lavalink_node(ctx.guild.id):
            log.warning("Lavalink was not ready after waiting for guild %s.", ctx.guild.id)
            log_event("play.lavalink.timeout", guild_id=ctx.guild.id, query=queries[0], query_count=len(queries))
            return False
        log_event("play.command.start", guild_id=ctx.guild.id, query=queries[0], query_count=len(queries))
        for query in queries:
            await self._invoke_silently(audio.command_play, ctx, query=query)
        success = await self._wait_for_track_after_play(ctx.guild.id)
        log_event("play.command.result", guild_id=ctx.guild.id, query=queries[0], query_count=len(queries), track_detected=success)
        return success

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
                log_event("play.track.detected", guild_id=guild_id)
                return True
            await asyncio.sleep(0.5)
        return self._track_from_player_for_controls(guild_id) is not None

    async def _station_feedback(self, ctx, bucket: str, message: str) -> str:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            await self._notice("No active radio station yet. Start one with `DjGoo radio <song>`.")
            log_event("radio.feedback.no_station", bucket=bucket)
            return "No active station"
        track = self._selected_track(ctx.guild.id, last=False)
        if track is None:
            await self._notice("I could not read the current track.")
            log_event("radio.feedback.no_current_track", guild_id=ctx.guild.id, bucket=bucket)
            return "No current track"
        data = self._track_data(track)
        self.stations.add_feedback(station["seed"], bucket, data)
        log_event("radio.feedback.saved", guild_id=ctx.guild.id, station=station["name"], bucket=bucket, track=data)
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
        self._lifecycle_transition(ctx.guild.id, "loading", reason="Stopping radio")
        await self._invoke_silently(audio.command_stop, ctx)
        verified = await self._wait_for_player_condition(
            ctx.guild.id,
            lambda player: player is None
            or (getattr(player, "current", None) is None and not list(getattr(player, "queue", []))),
        )
        self._lifecycle_transition(
            ctx.guild.id,
            "ended" if verified else "failed",
            reason="Radio stopped" if verified else "Player did not confirm radio stop",
        )
        if not verified:
            log_event("radio.stop.failed", guild_id=ctx.guild.id, reason="player_not_confirmed")
            return "Radio stop failed: player did not confirm stop"
        self.stations.clear_active(ctx.guild.id)
        self._clear_playback_state(ctx.guild.id)
        log_event("radio.stop", guild_id=ctx.guild.id, had_station=station is not None, station=(station or {}).get("name"))
        if station is None:
            await self._notice("Radio mode is already off.")
            return "Radio already off"
        await self._notice(f"Stopped `{station['name']}`. DjGoo will not keep topping up that station.")
        return f"Stopped {station['name']}"

    async def _stop_playback(self, audio, ctx) -> str:
        station = self.stations.get_active(ctx.guild.id)
        self._lifecycle_transition(ctx.guild.id, "loading", reason="Stopping playback")
        await self._invoke_silently(audio.command_stop, ctx)
        verified = await self._wait_for_player_condition(
            ctx.guild.id,
            lambda player: player is None
            or (getattr(player, "current", None) is None and not list(getattr(player, "queue", []))),
        )
        self._lifecycle_transition(
            ctx.guild.id,
            "ended" if verified else "failed",
            reason="Playback stopped" if verified else "Player did not confirm stop",
        )
        if not verified:
            log_event("play.stop.failed", guild_id=ctx.guild.id, reason="player_not_confirmed")
            return "Stop failed: player did not confirm stop"
        self.stations.clear_active(ctx.guild.id)
        self._clear_playback_state(ctx.guild.id)
        log_event("play.stop", guild_id=ctx.guild.id, cleared_station=(station or {}).get("name"))
        if station is not None:
            await self._notice(f"Stopped playback and turned off `{station['name']}`.")
        return "Stopped"

    async def _save_track(self, ctx, playlist_name: str, *, last: bool) -> str:
        track = self._selected_track(ctx.guild.id, last=last)
        if track is None:
            await self._notice("There is no current or previous song to save yet.")
            return "No track"
        result = self.playlists.add_track(playlist_name, self._track_data(track))
        log_event(
            "playlist.track.save",
            guild_id=ctx.guild.id,
            playlist=playlist_name,
            resolved_playlist=result.playlist_name,
            added=result.added,
            track=self._track_data(track),
            track_count=result.track_count,
        )
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
        data = {
            "title": getattr(track, "title", "") or info.get("title", ""),
            "uri": getattr(track, "uri", "") or info.get("uri", ""),
        }
        artwork = (
            getattr(track, "artwork_url", "")
            or info.get("artworkUrl", "")
            or info.get("artwork_url", "")
            or info.get("thumbnail", "")
        )
        if artwork:
            data["artwork_url"] = str(artwork).strip()
        elif data["uri"]:
            video_id = self._youtube_video_id(str(data["uri"]))
            if video_id:
                data["artwork_url"] = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
        duration = self._track_duration_seconds(track)
        if duration:
            data["duration_seconds"] = str(duration)
        return data

    async def _pause_or_resume(self, audio, ctx, *, want_pause: bool) -> None:
        try:
            player = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            await self._invoke_silently(audio.command_pause, ctx)
            return
        if player.paused == want_pause:
            await self._notice("Already paused." if want_pause else "Already playing.")
            return
        await self._invoke_silently(audio.command_pause, ctx)

    async def _toggle_pause(self, audio, ctx) -> str:
        try:
            player = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            await self._invoke_silently(audio.command_pause, ctx)
            return "Toggled pause."
        was_paused = player.paused
        await self._invoke_silently(audio.command_pause, ctx)
        return "Resumed." if was_paused else "Paused."

    async def _relative_volume(self, audio, ctx, delta: int) -> None:
        current = await audio.config.guild(ctx.guild).volume()
        await self._invoke_silently(audio.command_volume, ctx, vol=max(0, min(150, int(current) + delta)))

    async def _mark_station_skip(self, ctx) -> None:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            return
        track = self._selected_track(ctx.guild.id, last=False)
        if track is not None:
            data = self._track_data(track)
            self.stations.add_feedback(station["seed"], "skipped", data)
            self.stations.add_feedback(station["seed"], "banned", data)
            self.stations.mark_played(station["seed"], data)

    async def _skip_playback(self, audio, ctx) -> bool:
        station = self.stations.get_active(ctx.guild.id)
        previous = self._selected_track(ctx.guild.id, last=False)
        previous_key = self._track_key(previous) if previous is not None else ""
        self._lifecycle_transition(ctx.guild.id, "loading", reason="Skip sent to player")
        await self._mark_station_skip(ctx)
        if station is not None:
            await self._top_up_station_queue(ctx.guild.id)
        skipped_directly = False
        try:
            player = lavalink.get_player(ctx.guild.id)
            result = player.skip()
            if hasattr(result, "__await__"):
                await result
            skipped_directly = True
        except (NodeNotFound, PlayerNotFound):
            await self._invoke_silently(audio.command_skip, ctx)
        verified = await self._wait_for_player_condition(
            ctx.guild.id,
            lambda player: player is None
            or getattr(player, "current", None) is None
            or self._track_key(getattr(player, "current", None)) != previous_key,
        )
        lifecycle = getattr(self, "lifecycle", None)
        if verified and lifecycle is not None and previous_key:
            previous_operation = lifecycle.active_for_track(ctx.guild.id, previous_key)
            if previous_operation is not None:
                with contextlib.suppress(ValueError):
                    lifecycle.transition(
                        ctx.guild.id,
                        str(previous_operation.get("operation_id") or ""),
                        "skipped",
                        reason="Player confirmed this track was skipped",
                        track_key=previous_key,
                    )
        self._lifecycle_transition(
            ctx.guild.id,
            "skipped" if verified else "failed",
            reason="Player advanced" if verified else "Player did not advance after skip",
        )
        log_event(
            "play.skip",
            guild_id=ctx.guild.id,
            station=(station or {}).get("name"),
            direct=skipped_directly,
            verified=verified,
        )
        return verified

    async def _wait_for_player_condition(
        self,
        guild_id: int,
        predicate,
        *,
        timeout: float = 5.0,
    ) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout))
        while True:
            try:
                player = lavalink.get_player(guild_id)
            except (NodeNotFound, PlayerNotFound):
                player = None
            if predicate(player):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.1)

    def _lifecycle_transition(
        self,
        guild_id: int,
        state: str,
        *,
        reason: str,
        track: Dict[str, Any] | None = None,
        track_key: str = "",
    ) -> None:
        transition = getattr(self, "_transition_lifecycle", None)
        if callable(transition):
            transition(
                guild_id,
                state,
                reason=reason,
                track=track,
                track_key=track_key,
            )

    async def handle_station_track_start(self, guild, track) -> None:
        station = self.stations.get_active(guild.id)
        data = self._track_data(track)
        if self._should_reject_playing_track(data):
            log.info("DjGoo auto-skipping overlong or non-song track: %s", data.get("title", ""))
            log_event("radio.track.rejected_playing", guild_id=guild.id, reason="bad_title_or_duration", track=data)
            if station is not None:
                self.stations.add_feedback(station["seed"], "banned", data)
            await self._skip_rejected_station_track(guild.id)
            return
        if station is None:
            return
        if self._station_rejects_track(station, data):
            log.info("DjGoo auto-skipping repeated radio track in %s: %s", station["name"], data.get("title", ""))
            log_event("radio.track.rejected_playing", guild_id=guild.id, reason="station_rejects_track", station=station["name"], track=data)
            await self._skip_rejected_station_track(guild.id)
            return
        self.stations.mark_played(station["seed"], data)
        log_event("radio.track.played", guild_id=guild.id, station=station["name"], track=data)
        await self._send_payload(
            build_station_track_payload(
                station_name=station["name"],
                track=data,
                reason=self._station_reason(station),
            )
        )
        await self._top_up_station_queue(guild.id)

    def _station_rejects_track(self, station: Dict[str, Any], data: Dict[str, str]) -> bool:
        if self._should_reject_playing_track(data):
            return True
        key = track_key(data)
        blocked = []
        for bucket in ("banned", "skipped", "less_like", "recent"):
            blocked.extend(track for track in station.get(bucket, []) if isinstance(track, dict))
        return key in {track_key(track) for track in blocked}

    def _should_reject_playing_track(self, data: Dict[str, Any]) -> bool:
        if self._is_bad_radio_title(str(data.get("title", ""))):
            return True
        with contextlib.suppress(TypeError, ValueError):
            return int(data.get("duration_seconds") or 0) > MAX_TRACK_SECONDS
        return False

    def _is_bad_radio_title(self, title: str) -> bool:
        lowered = f" {re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()} "
        if re.search(r"\b\d+\s*(?:hour|hours|hr|hrs)\b", lowered):
            return True
        return any(phrase in lowered for phrase in RADIO_REJECT_TITLE_PHRASES)

    def _is_bad_radio_variant_title(self, title: str) -> bool:
        normalized = f" {re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()} "
        return any(
            phrase in normalized
            for phrase in (" remix ", " dub ", " megamix ", " mashup ", " bootleg ", " sped up ", " slowed ")
        )

    def _track_duration_seconds(self, track) -> int:
        info = getattr(track, "info", {}) or {}
        for value in (
            getattr(track, "length", None),
            getattr(track, "duration", None),
            info.get("length"),
            info.get("duration"),
        ):
            seconds = self._duration_value_seconds(value)
            if seconds:
                return seconds
        return 0

    def _duration_value_seconds(self, value) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            if ":" in value:
                return self._track_length_seconds(value)
            with contextlib.suppress(ValueError):
                value = float(value)
        if isinstance(value, (int, float)):
            if value > 10_000:
                return int(value / 1000)
            return int(value)
        return 0

    async def _skip_rejected_station_track(self, guild_id: int) -> None:
        await self._skip_rejected_track(guild_id, top_up_station=True)

    async def _skip_rejected_track(self, guild_id: int, *, top_up_station: bool = False) -> None:
        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            log_event("red_audio.rejected_skip.unavailable", guild_id=guild_id, has_audio=audio is not None, has_context=ctx is not None)
            return
        skipped_directly = False
        try:
            player = lavalink.get_player(guild_id)
            result = player.skip()
            if hasattr(result, "__await__"):
                await result
            skipped_directly = True
        except (NodeNotFound, PlayerNotFound):
            await self._invoke_silently(audio.command_skip, ctx)
        log_event(
            "red_audio.rejected_skip.sent",
            guild_id=guild_id,
            top_up_station=top_up_station,
            direct=skipped_directly,
        )
        if top_up_station:
            await self._top_up_station_queue(guild_id)

    async def handle_track_start(self, guild, track) -> None:
        log.info("DjGoo saw track start in guild %s: %s", guild.id, getattr(track, "title", track))
        data = self._track_data(track)
        log_event("red_audio.track.start", guild_id=guild.id, track=data)
        self._persist_player_state(guild.id, reason="track_start")
        if self._should_reject_playing_track(data):
            log.info("DjGoo blocking overlong or repeated-format track before controls: %s", data.get("title", ""))
            log_event("red_audio.track.blocked", guild_id=guild.id, reason="bad_title_or_duration", track=data)
            station = self.stations.get_active(guild.id)
            if station is not None:
                self.stations.add_feedback(station["seed"], "banned", data)
            await self._skip_rejected_track(guild.id, top_up_station=station is not None)
            return
        await self._send_playback_controls(guild, track, force=True)
        await self.handle_station_track_start(guild, track)

    async def handle_track_enqueue(self, guild, track) -> None:
        log.info("DjGoo saw track enqueue in guild %s: %s", guild.id, getattr(track, "title", track))
        log_event("red_audio.track.enqueue", guild_id=guild.id, track=self._track_data(track))
        self._persist_player_state(guild.id, reason="track_enqueue")

    async def handle_track_end(self, guild, track) -> None:
        log_event(
            "red_audio.track.end",
            guild_id=guild.id,
            track=self._track_data(track) if track is not None else {},
        )

    async def handle_queue_end(self, guild, track) -> None:
        station = self.stations.get_active(guild.id)
        log_event(
            "red_audio.queue.end",
            guild_id=guild.id,
            station=(station or {}).get("name"),
            track=self._track_data(track) if track is not None else {},
        )
        if station is not None:
            await self._top_up_station_queue(guild.id)
            return
        self._clear_playback_state(guild.id)
        now_playing = getattr(self, "now_playing", None)
        if now_playing is not None:
            now_playing.clear(guild.id)

    async def handle_red_track_enqueue_message(self, message) -> None:
        track = self._current_track_for_controls(message.guild.id)
        if track is not None:
            data = self._track_data(track)
            if self._should_reject_playing_track(data):
                log_event(
                    "red_audio.visible_enqueue.blocked",
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    reason="bad_title_or_duration",
                    track=data,
                )
                station = self.stations.get_active(message.guild.id)
                if station is not None:
                    self.stations.add_feedback(station["seed"], "banned", data)
                await self._skip_rejected_track(
                    message.guild.id,
                    top_up_station=station is not None,
                )
        log_event(
            "red_audio.visible_enqueue.ignored",
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            reason="Discord deck updates only after confirmed track start",
        )

    async def _send_controls_for_player(self, ctx: DjGooAudioContext) -> None:
        track = self._track_from_player_for_controls(ctx.guild.id)
        if track is None:
            log.warning("DjGoo found no current or queued track after play command in guild %s.", ctx.guild.id)
            log_event("discord.controls.no_track", guild_id=ctx.guild.id)
            return
        await self._send_playback_controls(ctx.guild, track, preferred_channel=ctx.channel)

    def _track_from_player_for_controls(self, guild_id: int):
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return None
        if player.current:
            return player.current
        if player.queue:
            return player.queue[0]
        return None

    def _current_track_for_controls(self, guild_id: int):
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return None
        return player.current

    async def _send_playback_controls(self, guild, track, *, preferred_channel=None, force: bool = False) -> None:
        data = self._track_data(track)
        if self._should_reject_playing_track(data):
            log_event("discord.controls.blocked_bad_track", guild_id=guild.id, track=data)
            return
        if force:
            self._mark_playback_controls_posted(guild.id, track)
        elif not self._should_post_playback_controls(guild.id, track):
            log_event("discord.controls.skipped_duplicate", guild_id=guild.id, track=data)
            return
        channel = preferred_channel or self._best_text_channel(guild)
        if channel is None:
            log.warning("DjGoo could not find a text channel for playback controls in guild %s.", guild.id)
            log_event("discord.controls.no_channel", guild_id=guild.id)
            return
        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages:
            log.warning("DjGoo cannot send playback controls in #%s: missing send_messages.", channel)
            log_event("discord.controls.missing_permission", guild_id=guild.id, channel_id=channel.id)
            return
        station = self.stations.get_active(guild.id)
        embed = discord.Embed.from_dict(
            build_playback_control_embed(
                data,
                station_name=station["name"] if station else None,
            )
        )
        view = PlaybackControlsView(self, guild.id)
        try:
            content = f"Now playing: {data.get('title', 'Unknown track')}"[:2000]
            await channel.send(content=content, embed=embed, view=view)
            log.info(
                "DjGoo posted playback controls in #%s for %s.",
                channel,
                data.get("title", "unknown track"),
            )
            log_event("discord.controls.posted", guild_id=guild.id, channel_id=channel.id, track=data, station=(station or {}).get("name"))
        except (discord.HTTPException, discord.Forbidden):
            log.exception("DjGoo failed to send playback controls in #%s.", channel)
            log_event("discord.controls.failed", guild_id=guild.id, channel_id=getattr(channel, "id", None), track=data)

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

    def _mark_playback_controls_posted(self, guild_id: int, track) -> None:
        self._recent_control_posts[guild_id] = (self._track_key(track), time.monotonic())

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
        try:
            gaming_button = getattr(self, "handle_gaming_button", None)
            if callable(gaming_button):
                vote_message = await gaming_button(interaction, intent)
                if vote_message is not None:
                    await interaction.followup.send(vote_message, ephemeral=True)
                    return
            if intent == "skip":
                skipped = await self._skip_playback(audio, ctx)
                message = "Skipped." if skipped else "Skip failed: the player did not advance."
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
            log_event("radio.top_up.skipped", guild_id=guild_id, reason="no_active_station")
            return
        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            log_event("radio.top_up.skipped", guild_id=guild_id, reason="missing_audio_or_context")
            return
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            log_event("radio.top_up.skipped", guild_id=guild_id, reason="no_player")
            return
        if len(player.queue) >= 2:
            log_event("radio.top_up.skipped", guild_id=guild_id, reason="queue_already_buffered", queue_length=len(player.queue))
            return
        recommended = await self._recommended_radio_track(station)
        if recommended is None:
            log_event(
                "radio.top_up.skipped",
                guild_id=guild_id,
                station=station["name"],
                reason="no_clean_recommendation",
                queue_length=len(player.queue),
            )
            return
        query = recommended["uri"]
        log_event(
            "radio.top_up.play",
            guild_id=guild_id,
            station=station["name"],
            query=query,
            used_recommendation=bool(recommended),
            queue_length=len(player.queue),
        )
        await self._invoke(audio.command_play, ctx, query=query)

    async def _recommended_radio_track(self, station: Dict[str, Any]) -> Optional[Dict[str, str]]:
        last_track = station.get("last_track") if isinstance(station.get("last_track"), dict) else None
        seed_track = station.get("seed_track") if isinstance(station.get("seed_track"), dict) else None
        anchor = last_track or seed_track
        video_id = self._youtube_video_id((anchor or {}).get("uri", ""))
        if not video_id:
            seed_query = self._radio_seed_search_query(str(station.get("seed") or ""))
            seed_uri = await asyncio.to_thread(self._ytmusic_song_search_query, seed_query, True)
            video_id = self._youtube_video_id(seed_uri or "")
            if video_id:
                self.stations.set_seed_track(
                    str(station.get("seed") or seed_query),
                    {"title": seed_query, "uri": seed_uri},
                )
        if not video_id:
            log_event("radio.recommendation.skipped", station=station.get("name"), reason="missing_youtube_video_id")
            return None
        try:
            tracks = await asyncio.to_thread(self._ytmusic_watch_tracks, video_id)
        except Exception:
            log.exception("DjGoo could not fetch YouTube Music radio recommendations.")
            log_event("radio.recommendation.fetch_failed", station=station.get("name"), video_id=video_id)
            return None
        log_event("radio.recommendation.fetched", station=station.get("name"), video_id=video_id, count=len(tracks or []))
        return self._pick_recommended_track(station, tracks)

    async def _resolve_youtube_play_query(self, query: str) -> Optional[List[str]]:
        if not self._is_youtube_url(query):
            return None
        query = self._youtube_url_from_query(query)
        playlist_id = self._youtube_playlist_id(query)
        video_id = self._youtube_video_id(query)
        if playlist_id and self._is_real_youtube_playlist_id(playlist_id):
            tracks = await self._youtube_playlist_tracks(playlist_id)
            expanded = self._watch_tracks_to_queries(tracks, limit=MAX_PLAYLIST_EXPANSION_TRACKS)
            if expanded:
                log_event(
                    "play.youtube.playlist.expanded",
                    query=query,
                    playlist_id=playlist_id,
                    source_track_count=len(tracks),
                    queued_track_count=len(expanded),
                )
                return expanded
            if video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                log_event(
                    "play.youtube.dead_playlist_parameter_removed",
                    query=query,
                    playlist_id=playlist_id,
                    video_id=video_id,
                    resolved_query=video_url,
                )
                return [video_url]
            log_event("play.youtube.playlist.unavailable", query=query, playlist_id=playlist_id)
            return []
        if not video_id:
            return [query]
        tracks = await self._watch_playlist_tracks_for_url(video_id, playlist_id)
        if playlist_id and self._is_youtube_radio_playlist_id(playlist_id):
            expanded = self._watch_tracks_to_queries(tracks)
            if expanded:
                log_event(
                    "play.youtube.radio_url.expanded",
                    query=query,
                    playlist_id=playlist_id,
                    video_id=video_id,
                    track_count=len(expanded),
                )
                return expanded
            resolved = await self._resolve_dirty_youtube_title(query, tracks)
            return [resolved or query]
        first = self._first_watch_track(tracks)
        if first and self._is_bad_youtube_play_item(first):
            title = self._watch_track_display_title(first)
            if self._is_album_like_youtube_title(title):
                playlist_url = await self._resolve_dirty_youtube_playlist(title)
                if playlist_url:
                    expanded = await self._resolve_youtube_play_query(playlist_url)
                    if expanded:
                        log_event(
                            "play.youtube.bad_video.playlist_resolved",
                            query=query,
                            video_id=video_id,
                            title=title,
                            resolved_query=playlist_url,
                            queued_track_count=len(expanded),
                        )
                        return expanded
            resolved = await self._resolve_dirty_youtube_title(query, tracks)
            if resolved:
                log_event("play.youtube.bad_video.cleaned", query=query, video_id=video_id, resolved_query=resolved, first_track=first)
                return [resolved]
        return [query]

    async def _watch_playlist_tracks_for_url(self, video_id: str, playlist_id: str = ""):
        try:
            return await asyncio.to_thread(
                self._ytmusic_watch_tracks,
                video_id,
                playlist_id if playlist_id and not self._is_youtube_radio_playlist_id(playlist_id) else None,
                self._is_youtube_radio_playlist_id(playlist_id),
            )
        except Exception:
            log.exception("DjGoo could not inspect YouTube URL before playback.")
            log_event("play.youtube.inspect_failed", video_id=video_id, playlist_id=playlist_id)
            return []

    async def _youtube_playlist_tracks(self, playlist_id: str):
        normalized_id = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
        try:
            tracks = await asyncio.to_thread(self._ytdlp_playlist_tracks, normalized_id)
            if tracks:
                log_event(
                    "play.youtube.playlist.inspected",
                    playlist_id=normalized_id,
                    extractor="yt-dlp-strict",
                    track_count=len(tracks),
                )
                return tracks
        except Exception as exc:
            log.warning("yt-dlp could not inspect playlist %s: %s", normalized_id, type(exc).__name__)
            log_event(
                "play.youtube.playlist.inspect_failed",
                playlist_id=normalized_id,
                extractor="yt-dlp-strict",
                error=type(exc).__name__,
            )
        try:
            tracks = await asyncio.to_thread(self._ytmusic_playlist_tracks, normalized_id)
            log_event(
                "play.youtube.playlist.inspected",
                playlist_id=normalized_id,
                extractor="ytmusicapi-fallback",
                track_count=len(tracks),
            )
            return tracks
        except Exception as exc:
            log.warning("YouTube Music could not inspect playlist %s: %s", normalized_id, type(exc).__name__)
            log_event(
                "play.youtube.playlist.inspect_failed",
                playlist_id=normalized_id,
                extractor="ytmusicapi-fallback",
                error=type(exc).__name__,
            )
            return []

    async def _resolve_dirty_youtube_title(self, original_query: str, tracks) -> Optional[str]:
        first = self._first_watch_track(tracks)
        title = str((first or {}).get("title") or "").strip()
        artists = self._ytmusic_artists(first or {})
        search_text = self._clean_bad_youtube_title(title)
        if artists:
            search_text = f"{', '.join(artists)} - {search_text}"
        if not search_text:
            search_text = original_query
        resolved = await asyncio.to_thread(self.nuclear.resolve_track_query, search_text)
        log_event(
            "play.youtube.dirty_title.resolve",
            original_query=original_query,
            title=title,
            artists=artists,
            search_text=search_text,
            resolved_query=resolved,
        )
        return resolved

    async def _resolve_dirty_youtube_playlist(self, title: str) -> Optional[str]:
        search_text = self._clean_bad_youtube_title(title) or title
        try:
            playlists = await asyncio.to_thread(self._ytmusic_playlist_search, search_text)
        except Exception:
            log.exception("DjGoo could not search YouTube Music playlists for a bad video.")
            log_event("play.youtube.playlist_search_failed", title=title, search_text=search_text)
            return None
        for item in playlists or []:
            if not isinstance(item, dict):
                continue
            playlist_id = str(item.get("playlistId") or item.get("browseId") or "").strip()
            if playlist_id.startswith("VL"):
                playlist_id = playlist_id[2:]
            if not playlist_id or self._is_youtube_radio_playlist_id(playlist_id):
                continue
            item_title = str(item.get("title") or "").strip()
            if self._is_bad_radio_title(item_title) and not self._is_album_like_youtube_title(item_title):
                continue
            resolved = f"https://www.youtube.com/playlist?list={playlist_id}"
            log_event("play.youtube.playlist_search.accepted", title=title, search_text=search_text, playlist_title=item_title, playlist_id=playlist_id)
            return resolved
        log_event("play.youtube.playlist_search.empty", title=title, search_text=search_text, count=len(playlists or []))
        return None

    def _first_watch_track(self, tracks) -> Optional[Dict[str, Any]]:
        for item in tracks or []:
            if isinstance(item, dict) and str(item.get("videoId") or "").strip():
                return item
        return None

    def _watch_tracks_to_queries(self, tracks, *, limit: int = MAX_PLAY_EXPANSION_TRACKS) -> List[str]:
        queries: List[str] = []
        seen: set[str] = set()
        for item in tracks or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "").strip()
            title = str(item.get("title") or "").strip()
            if not video_id or not title or video_id in seen:
                continue
            seen.add(video_id)
            raw_duration = item.get(
                "duration_seconds",
                item.get("durationSeconds", item.get("duration", item.get("length", ""))),
            )
            if isinstance(raw_duration, (int, float)):
                duration_seconds = int(raw_duration)
            else:
                duration_seconds = self._track_length_seconds(str(raw_duration or ""))
            data = {
                "title": self._watch_track_display_title(item),
                "uri": f"https://www.youtube.com/watch?v={video_id}",
                "duration_seconds": str(duration_seconds or 0),
            }
            if self._should_reject_playing_track(data):
                log_event("play.youtube.expansion.rejected", reason="bad_title_or_duration", track=data)
                continue
            queries.append(data["uri"])
            if len(queries) >= limit:
                break
        return queries

    def _watch_track_display_title(self, item: Dict[str, Any]) -> str:
        title = str(item.get("title") or "").strip()
        artists = self._ytmusic_artists(item)
        return f"{', '.join(artists)} - {title}" if artists else title

    def _ytmusic_artists(self, item: Dict[str, Any]) -> List[str]:
        return [
            str(artist.get("name", "")).strip()
            for artist in item.get("artists", [])
            if isinstance(artist, dict) and str(artist.get("name", "")).strip()
        ]

    def _is_bad_youtube_play_item(self, item: Dict[str, Any]) -> bool:
        data = {
            "title": self._watch_track_display_title(item),
            "uri": f"https://www.youtube.com/watch?v={str(item.get('videoId') or '').strip()}",
            "duration_seconds": str(self._track_length_seconds(str(item.get("length") or "")) or 0),
        }
        return self._should_reject_playing_track(data)

    def _clean_bad_youtube_title(self, title: str) -> str:
        cleaned = re.sub(r"[\[\(].*?(?:\d+\s*(?:hour|hours|hr|hrs)|loop|repeat|full album|album|mix|playlist|collection).*?[\]\)]", " ", title, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:\d+\s*(?:hour|hours|hr|hrs)|loop(?:ed)?|repeat(?:ed)?|full album|album|mix|playlist|collection|compilation)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_|")
        return cleaned

    def _is_album_like_youtube_title(self, title: str) -> bool:
        lowered = f" {re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()} "
        return any(
            phrase in lowered
            for phrase in (
                " full album ",
                " album ",
                " collection ",
                " compilation ",
                " greatest hits ",
                " playlist ",
                " mix ",
            )
        )

    def _ytmusic_watch_tracks(self, video_id: str, playlist_id: Optional[str] = None, radio: bool = False):
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        return self._ytmusic.get_watch_playlist(
            videoId=video_id,
            playlistId=playlist_id,
            limit=MAX_PLAY_EXPANSION_TRACKS,
            radio=radio,
        ).get("tracks", [])

    def _ytmusic_playlist_tracks(self, playlist_id: str):
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        return self._ytmusic.get_playlist(playlist_id, limit=MAX_PLAYLIST_EXPANSION_TRACKS).get("tracks", [])

    def _ytdlp_playlist_tracks(self, playlist_id: str):
        import yt_dlp

        class YtDlpLogger:
            def debug(self, message):
                log.debug("yt-dlp playlist: %s", message)

            def info(self, message):
                log.debug("yt-dlp playlist: %s", message)

            def warning(self, message):
                log.warning("yt-dlp playlist: %s", message)

            def error(self, message):
                log.warning("yt-dlp playlist: %s", message)

        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpLogger(),
                "extract_flat": "in_playlist",
                "skip_download": True,
                "ignoreerrors": True,
                "socket_timeout": 12,
                "retries": 1,
                "extractor_retries": 1,
                "playlistend": MAX_PLAYLIST_EXPANSION_TRACKS,
            }
        ) as extractor:
            info = extractor.extract_info(playlist_url, download=False)
        if not isinstance(info, dict):
            return []
        tracks = []
        for item in info.get("entries") or []:
            if not isinstance(item, dict):
                continue
            tracks.append(
                {
                    "videoId": item.get("id"),
                    "title": item.get("title"),
                    "duration_seconds": item.get("duration"),
                    "artists": (
                        [{"name": item.get("channel") or item.get("uploader")}]
                        if item.get("channel") or item.get("uploader")
                        else []
                    ),
                }
            )
        return tracks

    def _ytmusic_playlist_search(self, query: str):
        if self._ytmusic is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        return self._ytmusic.search(query, filter="playlists", limit=8)

    def _ytmusic_song_search_query(self, query: str, reject_radio_variants: bool = False) -> Optional[str]:
        if getattr(self, "_ytmusic", None) is None:
            from ytmusicapi import YTMusic

            self._ytmusic = YTMusic()
        try:
            results = self._ytmusic.search(query, filter="songs", limit=5)
        except Exception:
            log.exception("DjGoo could not search YouTube Music songs.")
            log_event("ytmusic.song_search.failed", query=query)
            return None
        for index, item in enumerate(results or []):
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "").strip()
            title = str(item.get("title") or "").strip()
            duration = self._track_length_seconds(str(item.get("duration") or ""))
            artists = self._ytmusic_artists(item)
            data = {
                "title": f"{', '.join(artists)} - {title}" if artists else title,
                "uri": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
                "duration_seconds": str(duration or 0),
            }
            bad_radio_variant = reject_radio_variants and self._is_bad_radio_variant_title(data["title"])
            if not video_id or not title or self._should_reject_playing_track(data) or bad_radio_variant:
                log_event("ytmusic.song_search.rejected", query=query, index=index, track=data)
                continue
            resolved = data["uri"]
            log_event("ytmusic.song_search.accepted", query=query, index=index, track=data, resolved_query=resolved)
            return resolved
        log_event("ytmusic.song_search.empty", query=query, count=len(results or []))
        return None

    def _pick_recommended_track(self, station: Dict[str, Any], tracks) -> Optional[Dict[str, str]]:
        candidates = []
        for item in tracks or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "").strip()
            title = str(item.get("title") or "").strip()
            if not video_id or not title:
                log_event("radio.recommendation.rejected", reason="missing_video_or_title", raw=item)
                continue
            if self._track_length_seconds(str(item.get("length") or "")) > 600:
                log_event("radio.recommendation.rejected", reason="overlong", title=title, length=item.get("length"))
                continue
            artists = [
                str(artist.get("name", "")).strip()
                for artist in item.get("artists", [])
                if isinstance(artist, dict) and str(artist.get("name", "")).strip()
            ]
            display_title = f"{', '.join(artists)} - {title}" if artists else title
            if self._is_bad_radio_variant_title(display_title):
                log_event("radio.recommendation.rejected", reason="alternate_version", title=display_title)
                continue
            candidate = {"title": display_title, "uri": f"https://www.youtube.com/watch?v={video_id}"}
            if self._station_rejects_track(station, candidate):
                log_event("radio.recommendation.rejected", reason="station_rejects_track", candidate=candidate, station=station.get("name"))
                continue
            candidates.append(candidate)
        choice = random.choice(candidates) if candidates else None
        log_event("radio.recommendation.picked", station=station.get("name"), candidate_count=len(candidates), choice=choice)
        return choice

    def _youtube_video_id(self, uri: str) -> str:
        match = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", uri)
        return match.group(1) if match else ""

    def _youtube_url_from_query(self, query: str) -> str:
        markdown_link = re.search(
            r"\((https?://(?:www\.|music\.)?youtube\.com/[^)\s]+)\)",
            query,
            re.IGNORECASE,
        )
        plain_link = re.search(
            r"https?://(?:(?:www\.|music\.)?youtube\.com|youtu\.be)/[^\s<>\]]+",
            query,
            re.IGNORECASE,
        )
        if markdown_link:
            url = markdown_link.group(1)
        elif plain_link:
            url = plain_link.group(0)
        else:
            url = query
        return url.replace("\\_", "_").rstrip(".,;>)")

    def _youtube_playlist_id(self, uri: str) -> str:
        try:
            parsed = urlparse(uri)
        except ValueError:
            return ""
        values = parse_qs(parsed.query).get("list") or []
        if values:
            return str(values[0]).strip()
        match = re.search(r"(?:youtube\.com|music\.youtube\.com)/playlist\?[^ ]*list=([A-Za-z0-9_-]+)", uri)
        return match.group(1) if match else ""

    def _is_youtube_url(self, query: str) -> bool:
        lowered = query.lower()
        return "youtube.com/" in lowered or "youtu.be/" in lowered or "music.youtube.com/" in lowered

    def _is_youtube_radio_playlist_id(self, playlist_id: str) -> bool:
        return playlist_id.upper().startswith("RD")

    def _is_real_youtube_playlist_id(self, playlist_id: str) -> bool:
        upper = playlist_id.upper()
        return upper.startswith(("PL", "OLAK5UY", "VL", "UU", "LL")) and not self._is_youtube_radio_playlist_id(playlist_id)

    def _track_length_seconds(self, length: str) -> int:
        if not length:
            return 0
        parts = [int(part) for part in length.split(":") if part.isdigit()]
        total = 0
        for part in parts:
            total = total * 60 + part
        return total

    def _radio_search_query(self, seed: str) -> str:
        exclusions = " ".join(f"-{term}" for term in RADIO_SEARCH_EXCLUSIONS)
        return f"{seed} official music video {exclusions}"

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
