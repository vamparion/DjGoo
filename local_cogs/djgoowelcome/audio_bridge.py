from __future__ import annotations

import contextlib
import random
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import discord
import lavalink
from lavalink import NodeNotFound, PlayerNotFound

from voice.djgoo_playlists import DjGooPlaylists


class _NoopTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeCommand:
    def reset_cooldown(self, ctx):
        return None


class _FakeMessage:
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


class DjGooAudioBridge:
    def __init__(self, *, bot, project_root: Path, send_payload: Callable[[Dict[str, Any]], Any]):
        self.bot = bot
        self.project_root = project_root
        self.playlists = DjGooPlaylists(project_root / "data" / "djgoo-playlists.json")
        self._send_payload = send_payload

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
            if intent == "play":
                query = str(item.get("query", "")).strip()
                if not query:
                    await self._notice("I need a song name or URL.")
                    return "Missing query"
                await self._invoke(audio.command_play, ctx, query=query)
                return f"Playing {query}"
            if intent == "play_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=False)
            if intent == "shuffle_playlist":
                return await self._play_playlist(audio, ctx, str(item.get("playlist", "")), shuffle=True)
            if intent in {"save_current_to_playlist", "save_last_to_playlist"}:
                return await self._save_track(ctx, str(item.get("playlist", "")), last=intent == "save_last_to_playlist")
            if intent == "skip":
                await self._invoke(audio.command_skip, ctx)
                return "Skipped"
            if intent in {"pause", "resume"}:
                await self._pause_or_resume(audio, ctx, want_pause=intent == "pause")
                return intent.title()
            if intent == "stop":
                await self._invoke(audio.command_stop, ctx)
                return "Stopped"
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

    def _best_text_channel(self, guild):
        with contextlib.suppress(Exception):
            player = lavalink.get_player(guild.id)
            notify_channel_id = player.fetch("notify_channel")
            if notify_channel_id:
                channel = guild.get_channel(int(notify_channel_id))
                if channel is not None:
                    return channel
        if guild.system_channel is not None:
            return guild.system_channel
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if perms.send_messages:
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

    async def _relative_volume(self, audio, ctx, delta: int) -> None:
        current = await audio.config.guild(ctx.guild).volume()
        await self._invoke(audio.command_volume, ctx, vol=max(0, min(150, int(current) + delta)))

    async def _send_queue_summary(self, ctx) -> None:
        try:
            player = lavalink.get_player(ctx.guild.id)
        except (NodeNotFound, PlayerNotFound):
            await self._notice("There is nothing in the queue.")
            return
        lines = []
        if player.current:
            lines.append(f"Now: `{player.current.title}`")
        for index, track in enumerate(player.queue[:5], start=1):
            lines.append(f"{index}. `{track.title}`")
        await self._notice("\n".join(lines) if lines else "There is nothing in the queue.")

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
