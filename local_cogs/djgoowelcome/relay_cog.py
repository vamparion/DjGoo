from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
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
            djgoo_cog._remote_state,
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

    def _raw_secrets(self) -> dict[str, Any]:
        path = self.djgoo_cog._secrets_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _settings(self) -> dict[str, Any]:
        secrets = self._raw_secrets()
        gateway = secrets.get("voice_gateway", {})
        gateway = gateway if isinstance(gateway, dict) else {}
        relay = gateway.get("relay", {})
        return relay if isinstance(relay, dict) else {}

    def _discord_webhook_url(self) -> str:
        secrets = self._raw_secrets()
        gateway = secrets.get("voice_gateway", {})
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

    def _save_discord_webhook_url(self, value: str) -> None:
        normalized = normalize_discord_webhook_url(value)
        path = self.djgoo_cog._secrets_path()
        payload = self._raw_secrets()
        gateway = payload.get("voice_gateway")
        if not isinstance(gateway, dict):
            gateway = {}
            payload["voice_gateway"] = gateway
        settings = gateway.get("discord_relay")
        if not isinstance(settings, dict):
            settings = {}
            gateway["discord_relay"] = settings
        settings["enabled"] = True
        settings["webhook_url"] = normalized
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    async def _discord_webhook_is_alive(self) -> bool:
        if not self.discord_webhook_url:
            return False
        timeout = aiohttp.ClientTimeout(total=6, connect=3)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.discord_webhook_url) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _forget_discord_webhook(self) -> None:
        path = self.djgoo_cog._secrets_path()
        payload = self._raw_secrets()
        gateway = payload.get("voice_gateway")
        if isinstance(gateway, dict):
            settings = gateway.get("discord_relay")
            if isinstance(settings, dict):
                settings.pop("webhook_url", None)
        # The legacy top-level value is also a transport capability and must not
        # keep reviving a revoked route.
        payload.pop("webhook_url", None)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        self.discord_webhook_url = ""
        self.discord_webhook_id = 0

    async def _ensure_discord_webhook(self, ctx: commands.Context) -> bool:
        if self.discord_webhook_url:
            if await self._discord_webhook_is_alive():
                return True
            await asyncio.to_thread(self._forget_discord_webhook)
            log_event("voice.discord_relay.revoked_route_removed")
        channel = getattr(ctx, "channel", None)
        guild = getattr(ctx, "guild", None)
        create_webhook = getattr(channel, "create_webhook", None)
        if guild is None or not callable(create_webhook):
            await ctx.send(
                "DjGoo could not create its outbound encrypted bridge in this channel. "
                "Run the command in a normal server text channel."
            )
            return False
        bot_member = getattr(guild, "me", None)
        try:
            permissions = channel.permissions_for(bot_member)
            can_manage = bool(getattr(permissions, "manage_webhooks", False))
        except Exception:
            can_manage = False
        if not can_manage:
            await ctx.send(
                "DjGoo Link needs the **Manage Webhooks** permission in this channel "
                "to create its outbound encrypted bridge. No router port or inbound "
                "firewall rule is required after that permission is granted."
            )
            return False
        try:
            webhook = await create_webhook(
                name="DjGoo Link",
                reason="Outbound encrypted DjGoo Voice bridge",
            )
            normalized = normalize_discord_webhook_url(str(webhook.url))
            await asyncio.to_thread(
                self._save_discord_webhook_url,
                normalized,
            )
        except Exception as exc:
            log_event(
                "voice.discord_relay.provision_failed",
                error=type(exc).__name__,
                detail=str(exc),
            )
            await ctx.send(
                "DjGoo could not create its outbound encrypted bridge. Verify that "
                "the bot has **Manage Webhooks** in this channel and try again."
            )
            return False
        self.discord_webhook_url = normalized
        self.discord_webhook_id = discord_webhook_id(normalized)
        log_event(
            "voice.discord_relay.provisioned",
            webhook_id=str(self.discord_webhook_id),
            guild_id=getattr(guild, "id", 0),
            channel_id=getattr(channel, "id", 0),
        )
        return True

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
        if gateway is None or getattr(gateway, "_site", None) is None:
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
        if not await self._ensure_discord_webhook(ctx):
            return None
        return PairingEndpoint(
            transport="discord",
            endpoint=self.discord_webhook_url,
            security=self.identity.encryption_fingerprint_sha256,
            code=await self._new_pairing_code(ctx),
            room_id=self.identity.room_id,
            host_public_key=self.identity.encryption_public_b64,
        )

    async def web_invite(self, ctx: commands.Context) -> PairingInvite | None:
        if not await self._ensure_discord_webhook(ctx):
            return None
        capabilities = (
            "state.read", "queue.read", "playback.request", "playback.vote_skip",
            "playback.control", "radio.control", "radio.feedback",
        )
        code = await asyncio.to_thread(
            self.djgoo_cog._pairing_store.create_pairing_code,
            int(ctx.author.id), int(ctx.guild.id), 300,
            device_type="web", capabilities=capabilities,
        )
        endpoint = PairingEndpoint(
            transport="discord",
            endpoint=self.discord_webhook_url,
            security=self.identity.encryption_fingerprint_sha256,
            code=code,
            room_id=self.identity.room_id,
            host_public_key=self.identity.encryption_public_b64,
        )
        invite = PairingInvite(
            code="", endpoints=(endpoint,), expires_at=time.time() + 300,
            host_name="DjGoo Host", guild_name=getattr(ctx.guild, "name", ""),
        )
        invite.validate(allow_expired=True)
        return invite

    async def _relay_endpoint(
        self,
        ctx: commands.Context,
    ) -> PairingEndpoint | None:
        if self.client is None:
            return None
        task = self.client._task
        if task is None or task.done():
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

        discord_endpoint = await self._discord_endpoint(ctx)
        relay_endpoint = await self._relay_endpoint(ctx)
        if discord_endpoint is None and relay_endpoint is None:
            await ctx.send(
                "DjGoo Link will not issue another unreliable LAN-only invite. "
                "Grant the bot **Manage Webhooks** in this channel, or configure a "
                "hosted encrypted relay, then run `djgoolink pair` again."
            )
            return
        direct_endpoints = await self._direct_endpoints(ctx)
        endpoints: list[PairingEndpoint] = []
        if discord_endpoint is not None:
            endpoints.append(discord_endpoint)
        if relay_endpoint is not None:
            endpoints.append(relay_endpoint)
        endpoints.extend(direct_endpoints)

        invite = PairingInvite(
            code="",
            endpoints=tuple(endpoints),
            expires_at=time.time() + 300,
            host_name="DjGoo Host",
            guild_name=getattr(ctx.guild, "name", ""),
        )
        invite.validate(allow_expired=True)

        routes: list[str] = []
        if discord_endpoint is not None:
            routes.append("Discord-backed encrypted outbound route")
        if relay_endpoint is not None:
            routes.append("hosted encrypted outbound route")
        if direct_endpoints:
            routes.append(
                f"{len(direct_endpoints)} optional same-network route(s)"
            )
        route_text = ", ".join(routes)

        message = (
            "**DjGoo Link invite**\n\n"
            "1. Open **DjGoo Voice**.\n"
            "2. Copy the entire invite below.\n"
            "3. Select **Paste and connect**.\n\n"
            f"```\n{invite.to_uri()}\n```\n"
            f"Safety number: `{invite.safety_number()}`\n"
            f"Connection: {route_text}.\n\n"
            "The invite expires in five minutes. DjGoo Voice uses the encrypted "
            "outbound route first, so no router port forwarding or inbound recipient "
            "firewall access is required. Local discovery remains an optional backup."
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
            internet_route_required=True,
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
            if gateway is not None and getattr(gateway, "_site", None) is not None
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
            f"Discord encrypted outbound route: `{bool(self.discord_webhook_url)}`\n"
            f"Hosted encrypted outbound route: `{relay_ready}`\n"
            f"Optional same-network routes: `{len(direct_urls)}`\n"
            "Pairing requires at least one outbound route. Paired devices "
            "automatically retain every route in the invite and are individually "
            "revocable with `djgoo revoke <device-id>`."
        )
