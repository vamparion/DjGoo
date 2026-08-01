from __future__ import annotations

from redbot.core import commands

from voice.command_catalog import command_help_text


class DjGooGuide(commands.Cog):
    """Discover DjGoo controls without reading external documentation."""

    @commands.hybrid_command(name="djgoohelp", aliases=("djgoocommands",))
    async def djgoo_help(self, ctx: commands.Context) -> None:
        """Show voice, chat, and button controls."""
        await ctx.send(
            "**DjGoo controls**\n"
            "You can say these while holding your configured push-to-talk key, "
            "or type them after `DjGoo,`.\n\n"
            + command_help_text()
            + "\n\n**Connect another player**\n"
            "Run `/djgoolink pair` and send them the private one-field invite DjGoo DMs you."
        )
