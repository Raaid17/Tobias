"""Entrypoint for the Discord assistant bot.

Responsibilities kept here (and nowhere else):
  - build the bot instance and its intents
  - connect to the Lavalink audio node (with retry, since it may still be
    starting up alongside us in Docker)
  - load every feature module ("cog")
  - sync slash commands with Discord

Feature logic lives in `cogs/` (commands) and `services/` (reusable
capability logic). This file should stay small as the bot grows.
"""

from __future__ import annotations

import asyncio
import logging

import discord
import wavelink
from discord.ext import commands

import config
from core.logging import setup_logging

log = logging.getLogger("bot")

# Each feature is a self-contained module. Add new ones here (e.g. "cogs.ai").
INITIAL_COGS: list[str] = [
    "cogs.general",
    "cogs.music",
]


class AssistantBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands don't require any privileged intents. voice_states is
        # already included in the default intents, which the music module needs.
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,  # unused (slash-only) but required
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        """Runs once after login but before the bot is ready."""
        await self._connect_lavalink()
        await self._load_cogs()
        await self._sync_commands()

    async def _connect_lavalink(self, retries: int = 12, delay: float = 5.0) -> None:
        """Connect to the Lavalink node, retrying while it boots.

        In Docker the bot and Lavalink start together, so the node often isn't
        accepting connections for the first few seconds. We retry rather than
        crash, and the bot still runs (minus music) if Lavalink never appears.
        """
        node = wavelink.Node(uri=config.LAVALINK_URI, password=config.LAVALINK_PASSWORD)
        for attempt in range(1, retries + 1):
            try:
                await wavelink.Pool.connect(nodes=[node], client=self, cache_capacity=100)
                log.info("Lavalink connection initiated at %s", config.LAVALINK_URI)
                return
            except Exception as exc:  # noqa: BLE001 - we want to retry on anything
                log.warning(
                    "Lavalink connect attempt %d/%d failed: %s", attempt, retries, exc
                )
                if attempt < retries:
                    await asyncio.sleep(delay)
        log.error(
            "Could not reach Lavalink at %s after %d attempts; music commands "
            "will be unavailable.",
            config.LAVALINK_URI,
            retries,
        )

    async def _load_cogs(self) -> None:
        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:  # noqa: BLE001 - log and continue loading others
                log.exception("Failed to load extension: %s", ext)

    async def _sync_commands(self) -> None:
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(
                "Synced %d slash command(s) to dev guild %s",
                len(synced),
                config.DEV_GUILD_ID,
            )
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global slash command(s)", len(synced))

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)


async def main() -> None:
    setup_logging(config.LOG_LEVEL)
    config.validate()

    bot = AssistantBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)  # type: ignore[arg-type]


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
