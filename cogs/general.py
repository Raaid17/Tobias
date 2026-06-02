"""General-purpose commands used to verify the bot is wired up correctly."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! `{latency_ms} ms`", ephemeral=True
        )

    @app_commands.command(name="help", description="Show what this bot can do.")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🤖 Assistant Bot",
            description="A modular Discord assistant. Music is the first module.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🎵 Music",
            value=(
                "`/play <query|url>` — play or queue a track\n"
                "`/skip` — skip the current track\n"
                "`/queue` — show the queue\n"
                "`/nowplaying` — current track + controls\n"
                "`/pause` · `/resume` — pause/resume\n"
                "`/volume [0-200]` — show or set volume\n"
                "`/loop <off|track|queue>` — set loop mode\n"
                "`/shuffle` — shuffle the queue\n"
                "`/seek <time>` — jump to a position\n"
                "`/remove <n>` · `/clear` — manage the queue\n"
                "`/stop` — stop and clear the queue\n"
                "`/leave` — disconnect from voice"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛠️ General",
            value="`/ping` — latency check\n`/help` — this message",
            inline=False,
        )
        embed.set_footer(text="More modules (AI, reminders, …) coming soon.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
