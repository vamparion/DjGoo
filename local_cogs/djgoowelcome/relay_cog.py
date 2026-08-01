from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from redbot.core import commands

from voice.command_acceptance import AuthenticatedCommandProcessor
from voice.operational_log import log_event
from voice.relay_crypto import load_or_create_host_identity
from voice.relay_host import RelayHostClient


class DjGooRelay(commands.Cog):
    """Optional outbound-only encrypted relay transport for DjGoo Voice."""

    def __init__(self, bot, djgoo_cog, project_root: Path) -> None:
        self.bot = bot
        self.djgoo_cog = djgoo_cog
        self.project_root = project_root
        self.settings = self._settings()
        self.identity = load_or_create_host_identity(project_root / "data" / "relay-identity")
        self.processor = AuthenticatedCommandProcessor(
            djgoo_cog._pairing_store,
            djgoo_cog._remote_queue_path(),
            djgoo_cog._authorize_remote,
        )
        self.client: RelayHostClient | None = None
        self._startup_task: asyncio.Task[None] | None = None
        relay_url = str(self.settings.get("url") or "").strip()
        if bool(self.settings.get("enabled", False)) and relay_url:
            self.client = RelayHostClient(relay_url, self.identity, self.processor)
            self._startup_task = self.bot.loop.create_task(self._start())
        else:
            log_event("voice.relay.disabled")

    def _settings(self) -> dict[str, Any]:
        secrets = self.djgoo_cog._gateway_settings()
        relay = secrets.get("relay", {}) if isinstance(secrets, dict) else {}
        return relay if isinstance(relay, dict) else {}

    async def _start(self) -> None:
        await self.bot.wait_until_red_ready()
        assert self.client is not None
        self.client.start()
        log_event(
            "voice.relay.starting",
            relay_url=self.client.relay_url,
            room_id=self.client.room_id,
            encryption_fingerprint=self.client.encryption_fingerprint,
        )

    def cog_unload(self) -> None:
        if self._startup_task is not None:
            self._startup_task.cancel()
        if self.client is not None:
            self.bot.loop.create_task(self.client.stop())

    @commands.hybrid_group(name="djgoorelay", invoke_without_command=True)
    async def relay_group(self, ctx: commands.Context) -> None:
        """Manage outbound DjGoo Voice Relay pairing."""
        await ctx.send("Use `djgoorelay pair` or `djgoorelay status`.")

    @relay_group.command(name="pair")
    @commands.guild_only()
    async def relay_pair(self, ctx: commands.Context) -> None:
        """Create a private end-to-end encrypted relay pairing bundle."""
        if self.client is None:
            await ctx.send(
                "Outbound relay mode is not configured on this Host. "
                "Use `djgoo pair` for direct LAN pairing."
            )
            return
        code = await asyncio.to_thread(
            self.djgoo_cog._pairing_store.create_pairing_code,
            int(ctx.author.id),
            int(ctx.guild.id),
            300,
        )
        message = (
            "DjGoo Voice encrypted relay pairing\n\n"
            f"Connection: `relay`\n"
            f"Relay URL: `{self.client.relay_url.rstrip('/')}`\n"
            f"Pairing code: `{code}`\n"
            f"Relay room ID: `{self.client.room_id}`\n"
            f"Host encryption key: `{self.client.encryption_public_key}`\n"
            f"Host key fingerprint: `{self.client.encryption_fingerprint}`\n\n"
            "The code expires in five minutes and can be used once. "
            "The relay routes an encrypted envelope and cannot read the pairing code, device token, transcript, or command."
        )
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send("I could not DM you. Enable direct messages from this server and try again.")
            return
        await ctx.send("Encrypted relay pairing details were sent privately.", delete_after=12)
        log_event(
            "voice.relay.pairing.code_created",
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            room_id=self.client.room_id,
        )

    @relay_group.command(name="status")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def relay_status(self, ctx: commands.Context) -> None:
        """Show non-secret outbound relay identity and configuration."""
        if self.client is None:
            await ctx.send("DjGoo outbound relay is disabled.")
            return
        task = self.client._task
        running = bool(task is not None and not task.done())
        await ctx.send(
            "DjGoo outbound relay\n"
            f"Connected/reconnecting: `{running}`\n"
            f"Relay: `{self.client.relay_url.rstrip('/')}`\n"
            f"Room: `{self.client.room_id}`\n"
            f"Encryption fingerprint: `{self.client.encryption_fingerprint}`"
        )
