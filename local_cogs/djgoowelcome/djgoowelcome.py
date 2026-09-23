from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from urllib.parse import quote
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import aiohttp
import discord
from redbot.core import commands

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voice.command_gateway import AuthorizationResult, VoiceCommandGateway
from voice.command_parser import parse_command
from voice.command_queue import command_to_queue_item, drain_queue
from voice.mini_player_protocol import CommandReceiptStore
from voice.operational_log import log_event
from voice.pairing_store import DeviceIdentity, PairingStore
from control_panel.state import build_remote_state_snapshot
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
    "clear_queue",
    "remove_queue",
    "shuffle_queue",
    "repeat",
    "autoplay",
    "toggle_repeat",
    "toggle_autoplay",
    "station_ban_current",
    "undo_station_ban",
    "gaming_undo",
    "volume",
    "volume_up",
    "volume_down",
    "remote_playlist_action",
    "remote_station_action",
    "remote_settings",
    "remote_player_role",
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
        self._mini_receipts = CommandReceiptStore(
            PROJECT_ROOT / "data" / "mini-player-acks"
        )
        with contextlib.suppress(Exception):
            self.bot.add_view(PlaybackControlsView(self._audio_bridge, 0))

        self._pairing_store = PairingStore(
            PROJECT_ROOT / "data" / "djgoo-pairing.db",
            PROJECT_ROOT / "data" / "djgoo-pairing-secret.bin",
        )
        self._gateway: VoiceCommandGateway | None = self._build_gateway()
        self._gateway_ready = False
        self._gateway_task = (
            self.bot.loop.create_task(self._start_gateway()) if self._gateway is not None else None
        )
        self._queue_task = self.bot.loop.create_task(self._command_queue_loop())

    def cog_unload(self):
        native_play_command = getattr(self, "_djgoo_native_play_command", None)
        native_play_callback = getattr(self, "_djgoo_native_play_callback", None)
        if native_play_command is not None and native_play_callback is not None:
            native_play_command.callback = native_play_callback
            with contextlib.suppress(AttributeError):
                del native_play_command._djgoo_playlist_routing
        self._queue_task.cancel()
        if self._gateway_task is not None:
            self._gateway_task.cancel()
        if self._gateway is not None:
            self.bot.loop.create_task(self._gateway.stop())

    async def red_delete_data_for_user(self, **kwargs):
        user_id = kwargs.get("user_id")
        if user_id is None:
            return
        await asyncio.to_thread(self._pairing_store.delete_user, int(user_id))

    def _secrets_path(self) -> Path:
        configured = os.environ.get("DJGOO_SECRETS_FILE")
        if configured:
            return Path(configured)
        return PROJECT_ROOT / "config" / "secrets.json"

    def _gateway_settings(self) -> dict[str, Any]:
        secrets = load_secrets(self._secrets_path())
        configured = secrets.get("voice_gateway", {})
        return configured if isinstance(configured, dict) else {}

    def _build_gateway(self) -> VoiceCommandGateway | None:
        settings = self._gateway_settings()
        if not bool(settings.get("enabled", True)):
            log_event("voice.gateway.disabled")
            return None
        identity = ensure_tls_identity(
            PROJECT_ROOT / "data" / "certs" / "voice-gateway.crt.pem",
            PROJECT_ROOT / "data" / "certs" / "voice-gateway.key.pem",
        )
        return VoiceCommandGateway(
            self._pairing_store,
            self._remote_queue_path(),
            self._authorize_remote,
            identity,
            host=str(settings.get("bind_host") or "0.0.0.0"),
            port=int(settings.get("port") or 49178),
        )

    async def _start_gateway(self) -> None:
        assert self._gateway is not None
        await self.bot.wait_until_red_ready()
        try:
            await self._gateway.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._gateway_ready = False
            log.exception("DjGoo Voice Gateway failed to start")
            log_event("voice.gateway.start_failed", error=type(exc).__name__, detail=str(exc))
            return
        self._gateway_ready = True
        log_event(
            "voice.gateway.ready",
            bind_host=self._gateway.host,
            port=self._gateway.port,
            fingerprint=self._gateway.fingerprint,
        )

    def _advertised_gateway_url(self) -> str:
        settings = self._gateway_settings()
        configured = str(settings.get("advertise_url") or "").strip().rstrip("/")
        if configured:
            return configured
        try:
            address = socket.gethostbyname(socket.gethostname())
        except OSError:
            address = "127.0.0.1"
        if not address or address.startswith("127."):
            address = "127.0.0.1"
        port = self._gateway.port if self._gateway is not None else int(settings.get("port") or 49178)
        return f"https://{address}:{port}"

    async def _authorize_remote(self, identity: DeviceIdentity, intent: str) -> AuthorizationResult:
        guild = self.bot.get_guild(identity.guild_id)
        if guild is None:
            return AuthorizationResult(False, "The paired Discord server is not available")
        member = guild.get_member(identity.user_id)
        if member is None:
            with contextlib.suppress(Exception):
                member = await guild.fetch_member(identity.user_id)
        if member is None:
            return AuthorizationResult(False, "The paired Discord member is not available")
        voice_state = getattr(member, "voice", None)
        member_channel = getattr(voice_state, "channel", None)
        if member_channel is None and intent != "state.read":
            return AuthorizationResult(False, "Join a Discord voice channel before using DjGoo Voice")

        voice_client = getattr(guild, "voice_client", None)
        bot_channel = getattr(voice_client, "channel", None)
        if bot_channel is not None and member_channel is not None and int(bot_channel.id) != int(member_channel.id):
            return AuthorizationResult(False, "Join the same voice channel as DjGoo")
        if bot_channel is None and intent != "state.read" and intent not in JOINING_REMOTE_INTENTS:
            return AuthorizationResult(False, "Start a song or radio station before using that control")

        permissions = getattr(member, "guild_permissions", None)
        is_owner = int(member.id) == int(guild.owner_id)
        is_manager = bool(getattr(permissions, "manage_guild", False)) or is_owner
        actor_role = "host" if is_owner else ("moderator" if is_manager else "member")
        if intent in DESTRUCTIVE_REMOTE_INTENTS and not is_manager:
            return AuthorizationResult(False, "That command requires Manage Server or server ownership")
        return AuthorizationResult(
            True,
            voice_channel_id=int(member_channel.id) if member_channel is not None else 0,
            actor_role=actor_role,
        )

    async def _remote_state(self, identity: DeviceIdentity) -> Dict[str, Any]:
        guild = self.bot.get_guild(identity.guild_id)
        member = guild.get_member(identity.user_id) if guild is not None else None
        permissions = getattr(member, "guild_permissions", None)
        is_owner = bool(
            guild is not None
            and member is not None
            and int(member.id) == int(guild.owner_id)
        )
        is_manager = is_owner or bool(getattr(permissions, "manage_guild", False))
        actor_role = "host" if is_owner else ("moderator" if is_manager else "member")
        display_name = str(getattr(member, "display_name", "") or "Discord member")
        await asyncio.to_thread(
            self._pairing_store.update_presence, identity.device_id, display_name, actor_role
        )
        state = await asyncio.to_thread(
            build_remote_state_snapshot,
            PROJECT_ROOT,
            privileged=is_manager,
        )
        if is_manager:
            devices = await asyncio.to_thread(self._pairing_store.list_guild_devices, identity.guild_id)
            players: Dict[int, Dict[str, Any]] = {}
            for device in devices:
                paired_member = guild.get_member(device.user_id) if guild is not None else None
                paired_permissions = getattr(paired_member, "guild_permissions", None)
                paired_owner = bool(guild is not None and paired_member is not None and int(paired_member.id) == int(guild.owner_id))
                paired_role = "host" if paired_owner else ("moderator" if bool(getattr(paired_permissions, "manage_guild", False)) else "member")
                paired_name = str(getattr(paired_member, "display_name", "") or device.display_name or f"Discord user {device.user_id}")
                if paired_member is not None and (paired_name != device.display_name or paired_role != device.role):
                    await asyncio.to_thread(self._pairing_store.update_presence, device.device_id, paired_name, paired_role)
                player = players.setdefault(device.user_id, {
                    "id": str(device.user_id), "discord_user_id": str(device.user_id),
                    "username": paired_name, "role": paired_role, "device_name": device.device_name,
                    "device_type": device.device_type, "last_seen": device.last_seen_at,
                    "online": False, "device_count": 0,
                })
                player["device_count"] += 1
                player["online"] = bool(player["online"] or time.time() - device.last_seen_at <= 90)
                if device.last_seen_at >= float(player["last_seen"]):
                    player.update({"last_seen": device.last_seen_at, "device_name": device.device_name})
                player["username"] = paired_name
                if paired_role in {"host", "moderator"}:
                    player["role"] = paired_role
            state["players"] = sorted(players.values(), key=lambda item: float(item["last_seen"]), reverse=True)
        state["session"] = {
            "role": actor_role,
            "display_name": display_name,
            "discord_user_id": str(identity.user_id),
            "guild_id": str(identity.guild_id),
            "device_id": identity.device_id,
        }
        return state

    def _cooldown_key(self, member, channel) -> Tuple[int, int]:
        return (int(member.id), int(channel.id))

    def _queue_path(self) -> Path:
        secrets = load_secrets(self._secrets_path())
        voice = secrets.get("voice", {}) if isinstance(secrets.get("voice", {}), dict) else {}
        configured = voice.get("queue_path", "")
        if configured:
            configured_path = Path(str(configured))
            return configured_path if configured_path.is_absolute() else PROJECT_ROOT / configured_path
        return PROJECT_ROOT / "data" / "voice-command-queue.jsonl"

    def _remote_queue_path(self) -> Path:
        settings = self._gateway_settings()
        configured = str(settings.get("queue_path") or "").strip()
        if configured:
            path = Path(configured)
            return path if path.is_absolute() else PROJECT_ROOT / path
        return PROJECT_ROOT / "data" / "remote-command-queue.jsonl"

    def _is_on_cooldown(self, member, channel) -> bool:
        key = self._cooldown_key(member, channel)
        now = time.monotonic()
        last_sent = self._last_sent.get(key, 0.0)
        if now - last_sent < self._cooldown_seconds:
            return True
        self._last_sent[key] = now
        return False

    async def _send_webhook_payload(self, payload: Dict[str, Any]) -> None:
        if await self._send_bot_payload(payload):
            return

        secrets = load_secrets(self._secrets_path())
        webhook_url = secrets.get("webhook_url", "")
        if not webhook_url:
            log.warning("DjGoo webhook is not configured. Edit config/secrets.json.")
            log_event("discord.webhook.missing")
            return

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(webhook_url, json=payload) as response:
                    log_event(
                        "discord.webhook.sent",
                        status=response.status,
                        embed_titles=[embed.get("title", "") for embed in payload.get("embeds", [])],
                        has_content=bool(payload.get("content")),
                    )
                    if response.status >= 400:
                        body = await response.text()
                        log.warning("DjGoo webhook failed with HTTP %s: %s", response.status, body[:500])
                        log_event("discord.webhook.failed", status=response.status, body=body[:500])
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.exception("DjGoo webhook request failed.")
            log_event("discord.webhook.exception")

    async def _send_bot_payload(self, payload: Dict[str, Any]) -> bool:
        content = str(payload.get("content") or "").strip() or None
        embeds = [
            discord.Embed.from_dict(item)
            for item in payload.get("embeds") or []
            if isinstance(item, dict)
        ]
        if content is None and not embeds:
            return True
        for guild in self.bot.guilds:
            channel = self._audio_bridge._best_text_channel(guild)
            if channel is None:
                continue
            try:
                await channel.send(content=content, embeds=embeds[:10])
            except (discord.HTTPException, discord.Forbidden):
                log.exception("DjGoo could not send a bot notification in #%s.", channel)
                log_event(
                    "discord.bot_notification.failed",
                    guild_id=guild.id,
                    channel_id=getattr(channel, "id", None),
                )
                continue
            log_event(
                "discord.bot_notification.sent",
                guild_id=guild.id,
                channel_id=channel.id,
                embed_titles=[embed.title or "" for embed in embeds],
                has_content=content is not None,
            )
            return True
        return False

    async def _handle_queued_item(self, item: dict[str, Any]) -> None:
        log_event(
            "voice.queue.item.received",
            type=item.get("type"),
            source=item.get("source"),
            intent=item.get("intent"),
            action=item.get("action"),
            query=item.get("query"),
            playlist=item.get("playlist"),
            raw=item.get("raw"),
            user_id=item.get("user_id"),
            device_id=item.get("device_id"),
            command_id=item.get("command_id"),
        )
        source = str(item.get("source") or "")
        command_id = str(item.get("command_id") or "")
        if source != "mini_player":
            if item.get("intent") not in FAST_CONTROL_INTENTS:
                await self._send_webhook_payload(build_voice_command_payload(item))
            else:
                await self._send_webhook_payload(build_fast_control_payload(item))
                log_event("voice.command.fast_notification_sent", intent=item.get("intent"))
        try:
            result = await self._audio_bridge.handle(item)
        except Exception as exc:
            if command_id:
                self._mini_receipts.write(
                    command_id,
                    intent=str(item.get("intent") or ""),
                    success=False,
                    result={
                        "status": "failed",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                )
            raise
        if command_id and source == "mini_player":
            self._mini_receipts.write(
                command_id,
                intent=str(item.get("intent") or ""),
                result=result,
            )
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
            user_id=item.get("user_id"),
            command_id=item.get("command_id"),
        )

    async def _command_queue_loop(self) -> None:
        await self.bot.wait_until_red_ready()
        log_event(
            "redbot.ready",
            guild_count=len(self.bot.guilds),
            audio_loaded=self.bot.get_cog("Audio") is not None,
            discord_ready=self.bot.is_ready(),
        )
        await self._audio_bridge.resume_saved_playback()
        next_heartbeat = 0.0
        queue_paths = (self._queue_path(), self._remote_queue_path())
        while True:
            try:
                now = time.monotonic()
                if now >= next_heartbeat:
                    log_event(
                        "redbot.heartbeat",
                        guild_count=len(self.bot.guilds),
                        audio_loaded=self.bot.get_cog("Audio") is not None,
                        discord_ready=self.bot.is_ready(),
                        voice_gateway_ready=self._gateway_ready,
                    )
                    publish_state = getattr(
                        self._audio_bridge,
                        "_publish_now_playing",
                        None,
                    )
                    if callable(publish_state):
                        for guild in self.bot.guilds:
                            publish_state(guild.id)
                    next_heartbeat = now + 5.0

                for queue_path in queue_paths:
                    items = drain_queue(queue_path)
                    if items:
                        log_event("voice.queue.drained", count=len(items), queue_path=str(queue_path))
                    for item in items:
                        try:
                            await self._handle_queued_item(item)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            log.exception(
                                "DjGoo failed one queued command; later commands will continue."
                            )
                            log_event(
                                "voice.queue.item.exception",
                                source=item.get("source"),
                                intent=item.get("intent"),
                                command_id=item.get("command_id"),
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("DjGoo voice command queue loop failed.")
                log_event("voice.queue.loop.exception")
            await asyncio.sleep(0.2)

    @commands.hybrid_group(name="djgoo", invoke_without_command=True)
    async def djgoo_group(self, ctx: commands.Context) -> None:
        """Manage DjGoo Voice Remote pairing."""
        await ctx.send("Use `djgoo pair`, `djgoo devices`, or `djgoo revoke <device-id>`. ")

    @commands.command(name="radio")
    @commands.guild_only()
    async def radio_command(
        self,
        ctx: commands.Context,
        *,
        seed: str = "",
    ) -> None:
        """Start or stop a persistent, station-specific DjGoo radio."""
        seed = seed.strip()
        if not seed:
            await ctx.send("Choose a station seed, for example `!radio 80s`.")
            return
        parsed = parse_command(f"radio {seed}", require_wake=False)
        item = command_to_queue_item(
            parsed,
            transcript=f"!radio {seed}",
            source="chat",
        )
        log_event(
            "chat.radio.command.received",
            guild_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            author_id=ctx.author.id,
            seed=seed,
            intent=parsed.intent,
        )
        result = await self._audio_bridge.handle_from_discord_context(item, ctx)
        log_event(
            "chat.radio.command.handled",
            guild_id=ctx.guild.id,
            seed=seed,
            intent=parsed.intent,
            result=result,
        )

    @djgoo_group.command(name="pair")
    @commands.guild_only()
    async def djgoo_pair(self, ctx: commands.Context) -> None:
        """Create a private, short-lived Voice Remote pairing code."""
        if self._gateway is None:
            await ctx.send("DjGoo Voice Gateway is disabled on this Host.")
            return
        code = await asyncio.to_thread(
            self._pairing_store.create_pairing_code,
            int(ctx.author.id),
            int(ctx.guild.id),
            300,
        )
        message = (
            "DjGoo Voice pairing details\n\n"
            f"Gateway URL: `{self._advertised_gateway_url()}`\n"
            f"Pairing code: `{code}`\n"
            f"TLS fingerprint: `{self._gateway.fingerprint}`\n\n"
            "The code expires in five minutes and can be used once. "
            "Keep the device token created during pairing private."
        )
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send("I could not send you a private message. Enable DMs from this server and try again.")
            return
        await ctx.send("Pairing details were sent to you privately.", delete_after=12)
        log_event("voice.pairing.code_created", user_id=ctx.author.id, guild_id=ctx.guild.id)

    @djgoo_group.command(name="web")
    @commands.guild_only()
    async def djgoo_web(self, ctx: commands.Context) -> None:
        """Privately pair this Discord member with the DjGoo web controls."""
        relay = self.bot.get_cog("DjGooRelay")
        if relay is None:
            await ctx.send("DjGoo web access is not ready on this Host.", delete_after=12)
            return
        invite = await relay.web_invite(ctx)
        if invite is None:
            return
        settings = self._gateway_settings().get("web", {})
        settings = settings if isinstance(settings, dict) else {}
        public_url = str(settings.get("public_url") or "https://vamparion.github.io/DjGoo/").strip().rstrip("/") + "/"
        link = public_url + f"?connect={int(time.time())}#pair=" + quote(invite.to_uri(), safe="")
        message = (
            "**DjGoo Web private invitation**\n\n"
            f"[Open DjGoo Web]({link})\n\n"
            "This one-time invitation expires in five minutes and is tied to your "
            "Discord account and this server. The Host accepts no inbound Internet connection."
        )
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send("I could not DM your private web invitation. Enable server DMs and try again.", delete_after=12)
            return
        await ctx.send("Your private DjGoo Web invitation was sent.", delete_after=12)
        log_event("web.pairing.invite_created", user_id=ctx.author.id, guild_id=ctx.guild.id)

    @djgoo_group.command(name="devices")
    @commands.guild_only()
    async def djgoo_devices(self, ctx: commands.Context) -> None:
        """List your active paired Voice Remote devices."""
        devices = await asyncio.to_thread(
            self._pairing_store.list_devices,
            int(ctx.author.id),
            int(ctx.guild.id),
        )
        if not devices:
            await ctx.send("You do not have any active DjGoo Voice devices.")
            return
        lines = [
            f"`{device.device_id}` — {device.device_name} ({device.device_type}) — last seen <t:{int(device.last_seen_at)}:R>"
            for device in devices
        ]
        await ctx.author.send("Your DjGoo Voice devices:\n" + "\n".join(lines))
        await ctx.send("Your active devices were sent to you privately.", delete_after=12)

    @djgoo_group.command(name="revoke")
    @commands.guild_only()
    async def djgoo_revoke(self, ctx: commands.Context, device_id: str) -> None:
        """Revoke one of your paired Voice Remote devices."""
        revoked = await asyncio.to_thread(
            self._pairing_store.revoke_device,
            device_id.strip(),
            int(ctx.author.id),
            int(ctx.guild.id),
        )
        if revoked:
            await ctx.send("That DjGoo Voice device has been revoked.")
            log_event("voice.device.revoked", user_id=ctx.author.id, guild_id=ctx.guild.id, device_id=device_id)
        else:
            await ctx.send("No active device with that ID belongs to you in this server.")

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
            "seek",
            "remove_queue",
            "shuffle_queue",
            "repeat",
            "autoplay",
            "favorite_current",
            "undo_station_ban",
            "gaming_undo",
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

    @commands.Cog.listener()
    async def on_red_audio_track_end(self, guild, track, requester):
        await self._audio_bridge.handle_track_end(guild, track)

    @commands.Cog.listener()
    async def on_red_audio_queue_end(self, guild, track, requester):
        await self._audio_bridge.handle_queue_end(guild, track)

    def _is_red_track_enqueue_message(self, message) -> bool:
        for embed in getattr(message, "embeds", []):
            if (getattr(embed, "title", "") or "").strip().lower() == "track enqueued":
                return True
        return False
