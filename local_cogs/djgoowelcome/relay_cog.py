from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from redbot.core import commands

from voice.command_acceptance import AuthenticatedCommandProcessor
from voice.discord_relay import (
    ERROR_PREFIX,
    REQUEST_PREFIX,
    decode_discord_request,
    delete_discord_message_after,
    discord_webhook_id,
    encode_discord_response,
    normalize_discord_webhook_url,
    update_discord_message,
)
from voice.network_routes import gateway_urls
from voice.operational_log import log_event
from voice.pairing_bundle import PairingEndpoint, PairingInvite
from voice.relay_crypto import load_or_create_host_identity
from voice.relay_envelope import handle_host_envelope
from voice.relay_host import RelayHostClient

from .helpers import load_secrets


class DjGooRelay(commands.Cog):
    """Secure local, Discord-backed, and hosted-relay DjGoo Link routes."""

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
        self.discord_webhook_url = self._discord_webhook_url()
        self.discord_webhook_id = (
            discord_webhook_id(self.discord_webhook_url)
            if self.discord_webhook_url
            else 0
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
        log_event(
            "voice.discord_relay.ready"
            if self.discord_webhook_url
            else "voice.discord_relay.disabled",
            webhook_id=(
                str(self.discord_webhook_id)
                if self.discord_webhook_id
                else ""
            ),
        )

    def _settings(self) -> dict[str, Any]:
        secrets = self.djgoo_cog._gateway_settings()
        relay = (
            secrets.get("relay", {})
            if isinstance(secrets, dict)
            else {}
        )
        return relay if isinstance(relay, dict) else {}

    def _discord_webhook_url(self) -> str:
        secrets = load_secrets(self.djgoo_cog._secrets_path())
        gateway = (
            secrets.get("voice_gateway", {})
            if isinstance(secrets, dict)
            else {}
        )
        gateway = gateway if isinstance(gateway, dict) else {}
        settings = gateway.get("discord_relay", {})
        settings = settings if isinstance(settings, dict) else {}
        if not bool(settings.get("enabled", True)):
            return ""
        configured = str(
            settings.get("webhook_url")
            or secrets.get("webhook_url")
            or ""
        ).strip()
        if not configured:
            return ""
        try:
            return normalize_discord_webhook_url(configured)
        except ValueError as exc:
            log_event(
                "voice.discord_relay.invalid",
                error=str(exc),
            )
            return ""

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

    @commands.Cog.listener()
    async def on_message(self, message) -> None:
        if not self.discord_webhook_url:
            return
        try:
            webhook_id = int(getattr(message, "webhook_id", 0) or 0)
        except (TypeError, ValueError):
            return
        if webhook_id != self.discord_webhook_id:
            return
        content = str(getattr(message, "content", "") or "")
        if not content.startswith(REQUEST_PREFIX):
            return

        message_id = str(getattr(message, "id", "") or "")
        if not message_id:
            return
        try:
            envelope = decode_discord_request(content)
            response = await handle_host_envelope(
                self.identity,
                self.processor,
                envelope,
            )
            response_content = encode_discord_response(response)
            event = "voice.discord_relay.request_handled"
        except Exception as exc:
            response_content = (
                ERROR_PREFIX
                + f"{type(exc).__name__}: {str(exc)[:240]}"
            )
            event = "voice.discord_relay.request_failed"
        try:
            await update_discord_message(
                self.discord_webhook_url,
                message_id,
                response_content,
            )
        except Exception as exc:
            log_event(
                "voice.discord_relay.response_failed",
                message_id=message_id,
                error=type(exc).__name__,
                detail=str(exc),
            )
            return
        log_event(event, message_id=message_id)
        self.bot.loop.create_task(
            delete_discord_message_after(
                self.discord_webhook_url,
                message_id,
                delay_seconds=60.0,
            )
        )

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

    async def _direct_endpoints(
        self,
        ctx: commands.Context,
    ) -> list[PairingEndpoint]:
        gateway = self.djgoo_cog._gateway
        if gateway is None:
            return []
        settings = self.djgoo_cog._gateway_settings()
        urls = gateway_urls(
            port=int(gateway.port),
            configured_url=str(
                settings.get("advertise_url") or ""
            ),
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

    async def _discord_endpoint(
        self,
        ctx: commands.Context,
    ) -> PairingEndpoint | None:
        if not self.discord_webhook_url:
            return None
        return PairingEndpoint(
            transport="discord",
            endpoint=self.discord_webhook_url,
            security=self.identity.encryption_fingerprint_sha256,
            code=await self._new_pairing_code(ctx),
            room_id=self.identity.room_id,
            host_public_key=self.identity.encryption_public_b64,
        )

    async def _relay_endpoint(
        self,
        ctx: commands.Context,
    ) -> PairingEndpoint | None:
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
        discord_endpoint = await self._discord_endpoint(ctx)
        relay_endpoint = await self._relay_endpoint(ctx)
        endpoints = [*direct_endpoints]
        if discord_endpoint is not None:
            endpoints.append(discord_endpoint)
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

        routes: list[str] = []
        if direct_endpoints:
            routes.append(
                f"{len(direct_endpoints)} same-network secure route(s)"
            )
        if discord_endpoint is not None:
            routes.append("Discord-backed encrypted internet fallback")
        if relay_endpoint is not None:
            routes.append("hosted encrypted internet fallback")
        route_text = ", ".join(routes)

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
            "identity automatically fails over between saved local and internet routes."
        )
        try:
            await ctx.author.send(message)
        except Exception:
            await ctx.send(
                "I could not send the private DjGoo Link invite. "
                "Enable direct messages from this server and try again."
            )
            return
        await ctx.send(
            "Your private DjGoo Link invite was sent.",
            delete_after=12,
        )
        log_event(
            "voice.link.pairing_invite_created",
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            direct_route_count=len(direct_endpoints),
            discord_relay_available=discord_endpoint is not None,
            relay_available=relay_endpoint is not None,
            route_specific_codes=True,
        )

    @link_group.command(name="status")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def link_status(self, ctx: commands.Context) -> None:
        """Show non-secret DjGoo Link state."""

        gateway = self.djgoo_cog._gateway
        direct_urls = (
            gateway_urls(
                port=int(gateway.port),
                configured_url=str(
                    self.djgoo_cog._gateway_settings().get(
                        "advertise_url"
                    )
                    or ""
                ),
            )
            if gateway is not None
            else []
        )
        relay_task = (
            self.client._task
            if self.client is not None
            else None
        )
        relay_ready = bool(
            relay_task is not None
            and not relay_task.done()
        )
        await ctx.send(
            "DjGoo Link\n"
            f"Same-network/public secure routes: `{len(direct_urls)}`\n"
            f"Discord internet fallback: `{bool(self.discord_webhook_url)}`\n"
            f"Hosted internet fallback: `{relay_ready}`\n"
            "Paired devices automatically try every saved route and are "
            "individually revocable with `djgoo revoke <device-id>`."
        )
