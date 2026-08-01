from redbot.core.bot import Red

from . import djgoowelcome as cog_module
from .remote_aware_bridge import RemoteAwareDjGooAudioBridge

# Keep the cog constructor stable while selecting the bridge implementation at the
# package boundary. This also lets source checkouts disable the remote transport
# without introducing a second playback authority.
cog_module.EnhancedDjGooAudioBridge = RemoteAwareDjGooAudioBridge
DjGooWelcome = cog_module.DjGooWelcome


async def setup(bot: Red) -> None:
    await bot.add_cog(DjGooWelcome(bot))
