from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import aiohttp
from redbot.core import commands

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice.command_parser import parse_command
from voice.command_queue import command_to_queue_item
from voice.command_queue import drain_queue
from voice.operational_log import log_event

from .audio_bridge import DjGooAudioBridge, PlaybackControlsView
from .helpers import (
    build_fast_control_payload,
    build_voice_command_payload,
    build_welcome_payload,
    load_secrets,
    parse_djgoo_chat_command,
    should_send_welcome,
)


log = logging.getLogger("red.djgoowelcome")
FAST_CONTROL_INTENTS = {
    "skip",
    "stop",
    "pause",
    "resume",
    "toggle_pause",
    "volume_up",
    "volume_down",
}


class DjGooWelcome(commands.Cog):
    """Posts a DjGoo command welcome screen when humans join voice."""

    def __init__(self, bot):
        self.bot = bot
        self._last_sent: Dict[Tuple[int, int], float] = {}
        self._cooldown_seconds = 300
        self._audio_bridge = DjGooAudioBridge(
            bot=self.bot,
            project_root=PROJECT_ROOT,
            send_payload=self._send_webhook_payload,
        )
        with contextlib.suppress(Exception):
            self.bot.add_view(PlaybackControlsView(self._audio_bridge, 0))
        self._queue_task = self.bot.loop.create_task(self._command_queue_loop())

    def cog_unload(self):
        self._queue_task.cancel()

    async def red_delete_data_for_user(self, **kwargs):
        return

    def _secrets_path(self) -> Path:
        configured = os.environ.get("DJGOO_SECRETS_FILE")
        if configured:
            return Path(configured)
        return Path.cwd() / "config" / "secrets.json"

    def _cooldown_key(self, member, channel) -> Tuple[int, int]:
        return (int(member.id), int(channel.id))

    def _queue_path(self) -> Path:
        secrets = load_secrets(self._secrets_path())
        configured = secrets.get("voice", {}).get("queue_path", "")
        if configured:
            return Path(configured)
        return Path.cwd() / "data" / "voice-command-queue.jsonl"

    def _is_on_cooldown(self, member, channel) -> bool:
        key = self._cooldown_key(member, channel)
        now = time.monotonic()
        last_sent = self._last_sent.get(key, 0.0)
        if now - last_sent < self._cooldown_seconds:
            return True
        self._last_sent[key] = now
        return False

    async def _send_webhook_payload(self, payload: Dict[str, Any]) -> None:
        secrets = load_secrets(self._secrets_path())
        webhook_url = secrets["webhook_url"]
        if not webhook_url:
            log.warning("DjGoo webhook is not configured. Edit config/secrets.json.")
            log_event("discord.webhook.missing")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as response:
                    log_event(
                        "discord.webhook.sent",
                        status=response.status,
                        embed_titles=[embed.get("title", "") for embed in payload.get("embeds", [])],
                        has_content=bool(payload.get("content")),
                    )
                    if response.status >= 400:
                        body = await response.text()
                        log.warning(
                            "DjGoo webhook failed with HTTP %s: %s",
                            response.status,
                            body[:500],
                        )
                        log_event("discord.webhook.failed", status=response.status, body=body[:500])
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("DjGoo webhook request failed.")
            log_event("discord.webhook.exception")

    async def _command_queue_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        log_event("redbot.ready", guild_count=len(self.bot.guilds))
        await self._audio_bridge.resume_saved_playback()
        while True:
            try:
                items = drain_queue(self._queue_path())
                if items:
                    log_event("voice.queue.drained", count=len(items), queue_path=str(self._queue_path()))
                for item in items:
                    log_event(
                        "voice.queue.item.received",
                        type=item.get("type"),
                        source=item.get("source"),
                        intent=item.get("intent"),
                        action=item.get("action"),
                        query=item.get("query"),
                        playlist=item.get("playlist"),
                        raw=item.get("raw"),
                    )
                    if item.get("intent") not in FAST_CONTROL_INTENTS:
                        await self._send_webhook_payload(build_voice_command_payload(item))
                    else:
                        await self._send_webhook_payload(build_fast_control_payload(item))
                        log_event("voice.command.fast_notification_sent", intent=item.get("intent"))
                    result = await self._audio_bridge.handle(item)
                    log.info(
                        "DjGoo handled %s command from %s: %s",
                        item.get("intent") or item.get("action") or item.get("type"),
                        item.get("source", "unknown"),
                        result,
                    )
                    log_event(
                        "voice.queue.item.handled",
                        type=item.get("type"),
                        source=item.get("source"),
                        intent=item.get("intent"),
                        result=result,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("DjGoo voice command queue loop failed.")
                log_event("voice.queue.loop.exception")
            await asyncio.sleep(0.2)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not should_send_welcome(member, before, after):
            return

        channel = after.channel
        if self._is_on_cooldown(member, channel):
            return

        payload = build_welcome_payload(member.display_name, channel.name)
        await self._send_webhook_payload(payload)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None:
            return
        if message.author == self.bot.user:
            if self._is_red_track_enqueue_message(message):
                await self._audio_bridge.handle_red_track_enqueue_message(message)
            return
        if getattr(message.author, "bot", False):
            return

        command_text = parse_djgoo_chat_command(message.content)
        if not command_text:
            return

        parsed = parse_command(message.content)
        log_event(
            "chat.command.received",
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            author_id=message.author.id,
            content=message.content,
            command_text=command_text,
            parsed_intent=parsed.intent,
            parsed_query=parsed.query,
            parsed_playlist=parsed.playlist,
        )
        bridge_intents = {
            "play",
            "play_album",
            "start_radio",
            "station_like_current",
            "station_more_like_current",
            "station_less_like_current",
            "station_ban_current",
            "station_status",
            "stop_radio",
            "save_current_to_playlist",
            "save_last_to_playlist",
            "play_playlist",
            "shuffle_playlist",
            "volume_up",
            "volume_down",
            "remove_current",
        }
        if parsed.intent in bridge_intents:
            result = await self._audio_bridge.handle(
                command_to_queue_item(parsed, transcript=message.content, source="chat")
            )
            log_event("chat.command.handled_by_bridge", intent=parsed.intent, result=result)
            return

        original_content = message.content
        message.content = f"!{command_text}"
        try:
            await self.bot.process_commands(message)
            log_event("chat.command.forwarded_to_redbot", command_text=command_text)
        finally:
            message.content = original_content

    @commands.Cog.listener()
    async def on_red_audio_track_start(self, guild, track, requester):
        await self._audio_bridge.handle_track_start(guild, track)

    @commands.Cog.listener()
    async def on_red_audio_track_enqueue(self, guild, track, requester):
        await self._audio_bridge.handle_track_enqueue(guild, track)

    def _is_red_track_enqueue_message(self, message) -> bool:
        for embed in getattr(message, "embeds", []):
            if (getattr(embed, "title", "") or "").strip().lower() == "track enqueued":
                return True
        return False
