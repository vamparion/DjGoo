from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import aiohttp
from redbot.core import commands

from tools.app_layout import package_root

PROJECT_ROOT = package_root(Path(__file__).resolve().parents[2])
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice.command_gateway import AuthorizationResult, VoiceCommandGateway
from voice.command_parser import parse_command
from voice.command_queue import command_to_queue_item, drain_queue
from voice.operational_log import log_event
from voice.pairing_store import DeviceIdentity, PairingStore
from voice.tls_identity import ensure_tls_identity

from .audio_bridge import PlaybackControlsView
from .enhanced_audio_bridge import EnhancedDjGooAudioBridge
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
    "seek",
    "remove_queue",
    "shuffle_queue",
}
DESTRUCTIVE_REMOTE_INTENTS = {
    "stop",
    "clear_queue",
    "remove_queue",
    "shuffle_queue",
    "repeat",
    "autoplay",
    "toggle_repeat",
    "toggle_autoplay",
    "station_ban_current",
    "undo_station_ban",
    "volume",
    "volume_up",
    "volume_down",
}
JOINING_REMOTE_INTENTS = {
    "play",
    "play_album",
    "play_playlist",
    "shuffle_playlist",
    "start_radio",
}


class DjGooWelcome(commands.Cog):
    """DjGoo chat, local voice, and paired Voice Remote integration."""

    def __init__(self, bot):
        self.bot = bot
        self._last_sent: Dict[Tuple[int, int], float] = {}
        self._cooldown_seconds = 300
        self._audio_bridge = EnhancedDjGooAudioBridge(
            bot=self.bot,
            project_root=PROJECT_ROOT,
            send_payload=self._send_webhook_payload,
        )
        with contextlib.suppress(Exception):
            self.bot.add_view(PlaybackControlsView(self._audio_bridge, 0))

        self._pairing_store = PairingStore(
            PROJECT_ROOT / "data" / "djgoo-pairing.db",
            PROJECT_ROOT / "data" / "djgoo-pairing-secret.bin",
        )
        self._gateway: VoiceCommandGateway | None = self._build_gateway()
        self._gateway_task = (
            self.bot.loop.create_task(self._start_gateway()) if self._gateway is not None else None
        )
        self._queue_task = self.bot.loop.create_task(self._command_queue_loop())
        self._presence_task = self.bot.loop.create_task(self._presence_loop())
        self._cleanup_task = self.bot.loop.create_task(self._cleanup_pairing_state_loop())

    def _secrets_path(self) -> Path:
        return PROJECT_ROOT / "config" / "secrets.json"

    def _remote_queue_path(self) -> Path:
        return PROJECT_ROOT / "data" / "voice-command-queue.jsonl"

    def _gateway_settings(self) -> dict[str, Any]:
        secrets = load_secrets(self._secrets_path())
        gateway = secrets.get("voice_gateway", {}) if isinstance(secrets, dict) else {}
        return gateway if isinstance(gateway, dict) else {}

    def _build_gateway(self) -> VoiceCommandGateway | None:
        settings = self._gateway_settings()
        if not bool(settings.get("enabled", True)):
            return None
        identity = ensure_tls_identity(PROJECT_ROOT / "data" / "voice-gateway")
        return VoiceCommandGateway(
            bind_host=str(settings.get("bind_host") or "0.0.0.0"),
            port=int(settings.get("port") or 47632),
            certificate_path=identity.certificate_path,
            private_key_path=identity.private_key_path,
            fingerprint=identity.fingerprint_sha256,
            pairing_store=self._pairing_store,
            queue_path=self._remote_queue_path(),
            authorize=self._authorize_remote,
        )

    async def _start_gateway(self) -> None:
        gateway = self._gateway
        if gateway is None:
            return
        try:
            await gateway.start()
        except Exception as exc:
            log_event(
                "voice.gateway.failed",
                error=type(exc).__name__,
                detail=str(exc),
            )

    async def _command_queue_loop(self) -> None:
        while True:
            try:
                for item in drain_queue(self._remote_queue_path()):
                    await self._audio_bridge.handle(item)
            except Exception as exc:
                log_event(
                    "voice.queue.failed",
                    error=type(exc).__name__,
                    detail=str(exc),
                )
            await asyncio.sleep(0.2)

    async def _presence_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        while True:
            try:
                guild_count = len(getattr(self.bot, "guilds", ()))
                audio_loaded = self.bot.get_cog("Audio") is not None
                discord_ready = bool(self.bot.is_ready())
                write = {
                    "guild_count": guild_count,
                    "audio_loaded": audio_loaded,
                    "discord_ready": discord_ready,
                    "voice_gateway_ready": bool(
                        self._gateway is not None
                        and getattr(self._gateway, "_site", None) is not None
                    ),
                }
                log_event("redbot.heartbeat", **write)
                from voice.health import write_heartbeat

                write_heartbeat(
                    "redbot",
                    project_root=PROJECT_ROOT,
                    fields=write,
                )
            except Exception as exc:
                log.debug("DjGoo heartbeat failed: %s", exc)
            await asyncio.sleep(5)

    async def _cleanup_pairing_state_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._pairing_store.cleanup)
            except Exception as exc:
                log.debug("DjGoo pairing cleanup failed: %s", exc)
            await asyncio.sleep(60)

    async def _send_webhook_payload(self, payload: dict[str, Any]) -> None:
        secrets = load_secrets(self._secrets_path())
        webhook_url = str(secrets.get("webhook_url") or "").strip()
        if not webhook_url:
            return
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(webhook_url, json=payload) as response:
                response.raise_for_status()

    async def _authorize_remote(
        self,
        device: DeviceIdentity,
        payload: dict[str, Any],
    ) -> AuthorizationResult:
        guild = self.bot.get_guild(int(device.guild_id))
        if guild is None:
            return AuthorizationResult(False, "DjGoo is no longer in the paired server")
        member = guild.get_member(int(device.discord_user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(device.discord_user_id))
            except Exception:
                return AuthorizationResult(False, "The paired Discord user is not in this server")
        voice = getattr(member, "voice", None)
        channel = getattr(voice, "channel", None)
        if channel is None:
            return AuthorizationResult(False, "Join a Discord voice channel before controlling DjGoo")
        me = guild.me
        bot_voice = getattr(getattr(me, "voice", None), "channel", None)
        if bot_voice is not None and bot_voice.id != channel.id:
            return AuthorizationResult(False, "Join the same voice channel as DjGoo")
        intent = str(payload.get("intent") or "").strip()
        permissions = getattr(member, "guild_permissions", None)
        if intent in DESTRUCTIVE_REMOTE_INTENTS and not (
            bool(getattr(permissions, "manage_guild", False))
            or int(member.id) == int(guild.owner_id)
        ):
            return AuthorizationResult(False, "This control requires Manage Server")
        return AuthorizationResult(
            True,
            discord_user_id=int(member.id),
            guild_id=int(guild.id),
            voice_channel_id=int(channel.id),
            display_name=str(getattr(member, "display_name", member.name)),
        )

    async def _dispatch_chat_command(self, message, command_text: str) -> None:
        parsed = parse_command(command_text)
        item = command_to_queue_item(
            parsed,
            transcript=message.content,
            source="discord_chat",
        )
        await self._audio_bridge.handle(item)

    @commands.Cog.listener()
    async def on_message(self, message) -> None:
        if message.guild is None or message.author == self.bot.user:
            return
        if getattr(message.author, "bot", False):
            return
        command_text = parse_djgoo_chat_command(message.content)
        if command_text:
            await self._dispatch_chat_command(message, command_text)
            return
        if not should_send_welcome(
            message.content,
            last_sent=self._last_sent,
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            cooldown_seconds=self._cooldown_seconds,
        ):
            return
        payload = build_welcome_payload(message.author.mention)
        await message.channel.send(**payload)
        self._last_sent[(message.guild.id, message.channel.id)] = time.monotonic()

    @commands.hybrid_group(name="djgoo", invoke_without_command=True)
    async def djgoo_group(self, ctx: commands.Context) -> None:
        """Show DjGoo controls."""
        payload = build_fast_control_payload()
        await ctx.send(**payload)

    @djgoo_group.command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a track through DjGoo."""
        item = command_to_queue_item(
            parse_command(f"play {query}"),
            transcript=f"play {query}",
            source="discord_command",
        )
        item["discord_user_id"] = int(ctx.author.id)
        item["guild_id"] = int(ctx.guild.id) if ctx.guild else 0
        await self._audio_bridge.handle(item)
        await ctx.send(f"DjGoo accepted: {query}")

    @djgoo_group.command(name="devices")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def devices(self, ctx: commands.Context) -> None:
        """List paired DjGoo Voice devices."""
        devices = await asyncio.to_thread(
            self._pairing_store.list_devices,
            int(ctx.guild.id),
        )
        if not devices:
            await ctx.send("No DjGoo Voice devices are paired with this server.")
            return
        lines = ["Paired DjGoo Voice devices:"]
        for device in devices:
            suffix = " (revoked)" if device.revoked_at else ""
            lines.append(
                f"- `{device.device_id}` — {device.device_name} — Discord `{device.discord_user_id}`{suffix}"
            )
        await ctx.send("\n".join(lines))

    @djgoo_group.command(name="revoke")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def revoke(self, ctx: commands.Context, device_id: str) -> None:
        """Revoke one paired DjGoo Voice device."""
        changed = await asyncio.to_thread(
            self._pairing_store.revoke_device,
            device_id,
            int(ctx.guild.id),
        )
        if changed:
            await ctx.send(f"Revoked DjGoo Voice device `{device_id}`.")
        else:
            await ctx.send("That device was not found or was already revoked.")

    def cog_unload(self) -> None:
        for task in (
            self._gateway_task,
            self._queue_task,
            self._presence_task,
            self._cleanup_task,
        ):
            if task is not None:
                task.cancel()
        if self._gateway is not None:
            self.bot.loop.create_task(self._gateway.stop())
