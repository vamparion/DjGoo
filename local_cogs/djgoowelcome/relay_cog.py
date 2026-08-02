from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from redbot.core import commands

from voice.command_acceptance import AuthenticatedCommandProcessor
from voice.network_routes import gateway_urls
from voice.operational_log import log_event
from voice.pairing_bundle import PairingEndpoint, PairingInvite
from voice.relay_crypto import load_or_create_host_identity
from voice.relay_host import RelayHostClient


class DjGooRelay(commands.Cog):
    """Secure direct and outbound-relay connections for DjGoo Link."""

    def __init__(self, bot, djgoo_cog, project_root: Path) -> None:
        self.bot = bot
        self.djgoo_cog = djgoo_cog
        self.project_root = project_root
        self.settings = self._settings()
        self.identity = load_or_create_host_identity(
            project_root / "data" / "relay-identity"
        )
        self.processor = AuthenticatedCommandProcessor(
            djgoo_cog._pairing_store,
            djgoo_cog._remote_queue_path(),
            djgoo_cog._authorize_remote,
        )
        self.client: RelayHostClient | None = None
        self._startup_task: asyncio.Task[None] | None = None
        relay_url = str(self.settings.get("url") or "").strip()
        if bool(self.settings.get("enabled", False)) and relay_url:
            self.client = RelayHostClient(
                relay_url,
                self.identity,
                self.processor,
            )
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

    @commands.hybrid_group(
        name="djgoolink",
        aliases=("djgoorelay",),
        invoke_without_command=True,
    )
    async def link_group(self, ctx: commands.Context) -> None:
        """Pair and inspect DjGoo recipient devices."""
        await ctx.send("Use `djgoolink pair` or `djgoolink status`.")

    async def _new_pairing_code(self, ctx: commands.Context) -> str:
        return await asyncio.to_thread(
            self.djgoo_cog._pairing_store.create_pairing_code,
            int(ctx.author.id),
            int(ctx.guild.id),
            300,
        )

    async def _direct_endpoints(self, ctx: commands.Context) -> list[PairingEndpoint]:
        gateway = self.djgoo_cog._gateway
        if gateway is None:
            return []
        settings = self.djgoo_cog._gateway_settings()
        urls = gateway_urls(
            port=int(gateway.port),
            configured_url=str(settings.get("advertise_url") or ""),
        )
        endpoints: list[PairingEndpoint] = []
        for url in urls:
            endpoints.append(
                PairingEndpoint(
                    transport="direct",
                    endpoint=url,
                    security=gateway.fingerprint,
                    code=await self._new_pairing_code(ctx),
                )
            )
        return endpoints

    async def _relay_endpoint(self, ctx: commands.Context) -> PairingEndpoint | None:
        if self.client is None:
            return None
        return PairingEndpoint(
            transport="relay",
            endpoint=self.client.relay_url.rstrip("/"),
            security=self.client.encryption_fingerprint,
            code=await self._new_pairing_code(ctx),
            room_id=self.client.room_id,
            host_public_key=self.client.encryption_public_key,
        )

    @link_group.command(name="pair")
    @commands.guild_only()
    async def link_pair(self, ctx: commands.Context) -> None:
        """Send one secure invite containing every available connection path."""

        direct_endpoints = await self._direct_endpoints(ctx)
        relay_endpoint = await self._relay_endpoint(ctx)
        endpoints = [*direct_endpoints]
        if relay_endpoint is not None:
            endpoints.append(relay_endpoint)
        if not endpoints:
            await ctx.send("DjGoo Link is disabled on this Host.")
            return

        invite = PairingInvite(
            code="",
            endpoints=tuple(endpoints),
            expires_at=time.time() + 300,
            host_name="DjGoo Host",
            guild_name=getattr(ctx.guild, "name", ""),
        )
        invite.validate(allow_expired=True)

        if direct_endpoints and relay_endpoint is not None:
            route_text = (
                f"{len(direct_endpoints)} same-network secure routes with an "
                "end-to-end encrypted internet fallback"
            )
        elif relay_endpoint is not None:
            route_text = "end-to-end encrypted internet link"
        else:
            route_text = f"{len(direct_endpoints)} same-network secure route(s)"

        message = (
            "**DjGoo Link invite**\n\n"
            "1. Open **DjGoo Voice**.\n"
            "2. Copy the entire invite below.\n"
            "3. Select **Paste and connect**.\n\n"
            f"```\n{invite.to_uri()}\n```\n"
            f"Safety number: `{invite.safety_number()}`\n"
            f"Connection: {route_text}.\n\n"
            "The invite expires in five minutes. DjGoo Voice probes every pinned "
            "route and uses the first reachable one. After pairing, the same device "
            "identity automatically fails over between saved local, public, and relay routes."
        )
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send(
                "I could not send the private DjGoo Link invite. Enable direct messages from this server and try again."
            )
            return
        await ctx.send("Your private DjGoo Link invite was sent.", delete_after=12)
        log_event(
            "voice.link.pairing_invite_created",
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            direct_route_count=len(direct_endpoints),
            relay_available=relay_endpoint is not None,
            route_specific_codes=True,
        )

    @link_group.command(name="status")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def link_status(self, ctx: commands.Context) -> None:
        """Show non-secret DjGoo Link state."""

        gateway = self.djgoo_cog._gateway
        direct_urls = gateway_urls(
            port=int(gateway.port),
            configured_url=str(
                self.djgoo_cog._gateway_settings().get("advertise_url") or ""
            ),
        ) if gateway is not None else []
        relay_task = self.client._task if self.client is not None else None
        relay_ready = bool(relay_task is not None and not relay_task.done())
        await ctx.send(
            "DjGoo Link\n"
            f"Same-network/public secure routes: `{len(direct_urls)}`\n"
            f"Encrypted internet fallback: `{relay_ready}`\n"
            "Paired devices automatically try every saved route and are individually "
            "revocable with `djgoo revoke <device-id>`."
        )
