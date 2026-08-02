import asyncio
from pathlib import Path

from redbot.core import commands
from redbot.core.bot import Red

from . import djgoowelcome as cog_module
from .guide_cog import DjGooGuide
from .relay_cog import DjGooRelay
from .remote_aware_bridge import RemoteAwareDjGooAudioBridge
from tools.windows_firewall import ensure_gateway_firewall
from voice.lan_discovery import DISCOVERY_PORT, LanDiscoveryResponder
from voice.operational_log import log_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMED_REQUEST_INTENTS = {"play_now", "queue_request"}


# Select the complete DjGoo bridge at the package boundary while retaining one
# playback authority. Third-party engine names stay behind this internal seam.
cog_module.EnhancedDjGooAudioBridge = RemoteAwareDjGooAudioBridge
cog_module.JOINING_REMOTE_INTENTS.update(TIMED_REQUEST_INTENTS)
DjGooWelcome = cog_module.DjGooWelcome


def _install_gateway_firewall_repair() -> None:
    if bool(getattr(DjGooWelcome, "_djgoo_gateway_firewall_repair", False)):
        return
    original_start_gateway = DjGooWelcome._start_gateway
    original_cog_unload = DjGooWelcome.cog_unload

    async def _start_gateway(self) -> None:
        gateway = self._gateway
        if gateway is not None:
            try:
                success, detail = await asyncio.to_thread(
                    ensure_gateway_firewall,
                    PROJECT_ROOT,
                    port=int(gateway.port),
                    discovery_port=DISCOVERY_PORT,
                )
            except Exception as exc:
                success, detail = False, f"{type(exc).__name__}: {exc}"
            log_event(
                "voice.gateway.firewall_checked",
                ready=success,
                detail=detail,
                port=int(gateway.port),
                discovery_port=DISCOVERY_PORT,
            )

        # Do not advertise a Host until the certificate-pinned TCP gateway has
        # completed its own startup. A discovery response must mean that the
        # returned address and port are ready for the recipient's TLS probe.
        await original_start_gateway(self)

        gateway = self._gateway
        if gateway is None:
            return
        discovery = getattr(self, "_djgoo_lan_discovery", None)
        if discovery is not None:
            return
        discovery = LanDiscoveryResponder(
            gateway_port=int(gateway.port),
            fingerprint=gateway.fingerprint,
            listen_port=DISCOVERY_PORT,
        )
        try:
            await discovery.start()
        except Exception as exc:
            log_event(
                "voice.gateway.discovery_failed",
                error=type(exc).__name__,
                detail=str(exc),
                port=DISCOVERY_PORT,
            )
        else:
            self._djgoo_lan_discovery = discovery
            log_event(
                "voice.gateway.discovery_ready",
                port=DISCOVERY_PORT,
                gateway_port=int(gateway.port),
            )

    def cog_unload(self):
        discovery = getattr(self, "_djgoo_lan_discovery", None)
        if discovery is not None:
            self.bot.loop.create_task(discovery.stop())
            self._djgoo_lan_discovery = None
        original_cog_unload(self)

    DjGooWelcome._start_gateway = _start_gateway
    DjGooWelcome.cog_unload = cog_unload
    DjGooWelcome._djgoo_gateway_firewall_repair = True


def _install_timed_chat_routing() -> None:
    if bool(getattr(DjGooWelcome, "_djgoo_timed_chat_routing", False)):
        return
    original_on_message = DjGooWelcome.on_message

    @commands.Cog.listener()
    async def on_message(self, message) -> None:
        if (
            message.guild is not None
            and message.author != self.bot.user
            and not getattr(message.author, "bot", False)
        ):
            command_text = cog_module.parse_djgoo_chat_command(
                message.content
            )
            if command_text:
                parsed = cog_module.parse_command(message.content)
                if parsed.intent in TIMED_REQUEST_INTENTS:
                    result = await self._audio_bridge.handle(
                        cog_module.command_to_queue_item(
                            parsed,
                            transcript=message.content,
                            source="chat",
                        )
                    )
                    cog_module.log_event(
                        "chat.command.handled_by_bridge",
                        intent=parsed.intent,
                        result=result,
                    )
                    return
        await original_on_message(self, message)

    DjGooWelcome.on_message = on_message
    DjGooWelcome._djgoo_timed_chat_routing = True


_install_gateway_firewall_repair()
_install_timed_chat_routing()


async def setup(bot: Red) -> None:
    djgoo = DjGooWelcome(bot)
    await bot.add_cog(djgoo)
    await bot.add_cog(DjGooGuide())
    await bot.add_cog(DjGooRelay(bot, djgoo, PROJECT_ROOT))
