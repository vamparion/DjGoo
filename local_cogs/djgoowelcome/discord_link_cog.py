from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import aiohttp
from redbot.core import commands

from voice.command_acceptance import AuthenticatedCommandProcessor
from voice.discord_link_host import DiscordLinkHostProcessor
from voice.discord_link_store import DiscordLinkStore
from voice.discord_link_transport import (
    REQUEST_PREFIX,
    RESPONSE_PREFIX,
    decode_discord_envelope,
    encode_discord_envelope,
)
from voice.operational_log import log_event
from voice.relay_crypto import load_or_create_host_identity


class DjGooDiscordLink(commands.Cog):
    """Use Discord only as an opaque encrypted DjGoo Link transport."""

    def __init__(self, bot, djgoo_cog, project_root: Path) -> None:
        self.bot = bot
        self.djgoo_cog = djgoo_cog
        self.project_root = project_root
        self.identity = load_or_create_host_identity(
            project_root / "data" / "relay-identity"
        )
        self.store = DiscordLinkStore(
            project_root / "data" / "discord-link-routes.json"
        )
        self.commands = AuthenticatedCommandProcessor(
            djgoo_cog._pairing_store,
            djgoo_cog._remote_queue_path(),
            djgoo_cog._authorize_remote,
        )
        self.processor = DiscordLinkHostProcessor(
            self.identity,
            self.commands,
        )
        self.djgoo_cog._discord_link_cog = self

    @property
    def encryption_public_key(self) -> str:
        return self.identity.encryption_public_b64

    @property
    def encryption_fingerprint(self) -> str:
        return self.identity.encryption_fingerprint_sha256

    def cog_unload(self) -> None:
        if getattr(self.djgoo_cog, "_discord_link_cog", None) is self:
            self.djgoo_cog._discord_link_cog = None

    async def _route_is_alive(self, route: dict[str, Any]) -> bool:
        url = str(route.get("webhook_url") or "")
        if not url:
            return False
        timeout = aiohttp.ClientTimeout(total=6, connect=3)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _candidate_channel(self, ctx: commands.Context):
        channel = getattr(ctx, "channel", None)
        if channel is not None and hasattr(channel, "create_webhook"):
            return channel
        return self.djgoo_cog._best_text_channel(ctx.guild)

    async def ensure_route(
        self,
        ctx: commands.Context,
    ) -> dict[str, Any] | None:
        existing = self.store.get_for_guild(ctx.guild.id)
        if existing is not None:
            if await self._route_is_alive(existing):
                return existing
            self.store.clear(ctx.guild.id)

        channel = self._candidate_channel(ctx)
        if channel is None or not hasattr(channel, "create_webhook"):
            log_event(
                "voice.discord_link.unavailable",
                guild_id=ctx.guild.id,
                reason="no_webhook_capable_channel",
            )
            return None
        permissions = channel.permissions_for(ctx.guild.me)
        if not bool(getattr(permissions, "manage_webhooks", False)):
            log_event(
                "voice.discord_link.unavailable",
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                reason="missing_manage_webhooks",
            )
            return None
        try:
            webhook = await channel.create_webhook(
                name="DjGoo Link",
                reason="Encrypted DjGoo Voice recipient connection",
            )
        except Exception as exc:
            log_event(
                "voice.discord_link.create_failed",
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                error=type(exc).__name__,
            )
            return None

        url = str(getattr(webhook, "url", "") or "")
        if not url:
            with contextlib.suppress(Exception):
                await webhook.delete(
                    reason="Incomplete DjGoo Link webhook"
                )
            return None
        self.store.set(
            ctx.guild.id,
            channel_id=channel.id,
            webhook_id=webhook.id,
            webhook_url=url,
        )
        route = self.store.get_for_guild(ctx.guild.id)
        log_event(
            "voice.discord_link.created",
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            webhook_id=webhook.id,
        )
        return route

    async def _edit_webhook_message(
        self,
        webhook_url: str,
        message_id: int,
        content: str,
    ) -> bool:
        url = f"{webhook_url.rstrip('/')}/messages/{int(message_id)}"
        timeout = aiohttp.ClientTimeout(total=10, connect=4)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.patch(
                    url,
                    json={
                        "content": content,
                        "allowed_mentions": {"parse": []},
                    },
                ) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def _delete_webhook_message_later(
        self,
        webhook_url: str,
        message_id: int,
        delay_seconds: float = 90.0,
    ) -> None:
        await asyncio.sleep(delay_seconds)
        url = f"{webhook_url.rstrip('/')}/messages/{int(message_id)}"
        timeout = aiohttp.ClientTimeout(total=8, connect=3)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.delete(url):
                    pass
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    @commands.Cog.listener()
    async def on_message(self, message) -> None:
        content = str(getattr(message, "content", "") or "")
        webhook_id = getattr(message, "webhook_id", None)
        guild = getattr(message, "guild", None)
        if (
            webhook_id is None
            or guild is None
            or not content.startswith(REQUEST_PREFIX)
        ):
            return
        route = self.store.get_for_webhook(int(webhook_id))
        if route is None:
            return
        if (
            int(route.get("guild_id") or 0) != int(guild.id)
            or int(route.get("channel_id") or 0)
            != int(getattr(message.channel, "id", 0) or 0)
        ):
            return

        try:
            envelope = decode_discord_envelope(
                REQUEST_PREFIX,
                content,
            )
            response = await self.processor.handle(
                envelope,
                webhook_id=str(webhook_id),
            )
            encoded = encode_discord_envelope(
                RESPONSE_PREFIX,
                response,
            )
        except Exception as exc:
            log_event(
                "voice.discord_link.request_rejected",
                guild_id=guild.id,
                webhook_id=webhook_id,
                message_id=message.id,
                error=type(exc).__name__,
            )
            return

        webhook_url = str(route.get("webhook_url") or "")
        edited = await self._edit_webhook_message(
            webhook_url,
            message.id,
            encoded,
        )
        log_event(
            "voice.discord_link.response_sent",
            guild_id=guild.id,
            webhook_id=webhook_id,
            message_id=message.id,
            success=edited,
        )
        if edited:
            self.bot.loop.create_task(
                self._delete_webhook_message_later(
                    webhook_url,
                    message.id,
                )
            )
