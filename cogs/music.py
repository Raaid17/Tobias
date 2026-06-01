"""Music module: slash commands for voice playback via Lavalink/wavelink.

Each Discord server (guild) gets its own player and queue automatically —
wavelink keys players by guild, so state never leaks between servers.
"""

from __future__ import annotations

import logging

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from services import audio

log = logging.getLogger("music")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ----- wavelink events -------------------------------------------------

    @commands.Cog.listener()
    async def on_wavelink_node_ready(
        self, payload: wavelink.NodeReadyEventPayload
    ) -> None:
        log.info(
            "Lavalink node '%s' ready (resumed=%s)",
            payload.node.identifier,
            payload.resumed,
        )

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        """Announce the track in the channel where /play was used."""
        player = payload.player
        if player is None:
            return
        home: discord.abc.Messageable | None = getattr(player, "home", None)
        if home is not None:
            try:
                await home.send(embed=audio.now_playing_embed(player))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Leave the voice channel after a period of inactivity."""
        home: discord.abc.Messageable | None = getattr(player, "home", None)
        if home is not None:
            try:
                await home.send("👋 Left the voice channel due to inactivity.")
            except discord.HTTPException:
                pass
        await player.disconnect()

    # ----- helpers ---------------------------------------------------------

    async def _get_player(
        self, interaction: discord.Interaction, *, connect: bool = False
    ) -> wavelink.Player | None:
        """Return the guild's player, optionally connecting to the caller's
        voice channel. Sends an ephemeral error and returns None on failure."""
        player: wavelink.Player | None = interaction.guild.voice_client  # type: ignore[assignment]

        if player is not None:
            return player

        if not connect:
            return None

        author = interaction.user
        if (
            not isinstance(author, discord.Member)
            or author.voice is None
            or author.voice.channel is None
        ):
            await self._respond(
                interaction, "You need to be in a voice channel first.", error=True
            )
            return None

        try:
            player = await author.voice.channel.connect(cls=wavelink.Player)
        except discord.ClientException:
            await self._respond(
                interaction, "I couldn't connect to your voice channel.", error=True
            )
            return None

        player.autoplay = wavelink.AutoPlayMode.partial  # auto-advance the queue
        player.inactive_timeout = audio.INACTIVE_TIMEOUT
        await player.set_volume(audio.DEFAULT_VOLUME)
        return player

    @staticmethod
    async def _respond(
        interaction: discord.Interaction, content: str, *, error: bool = False
    ) -> None:
        """Reply whether or not the interaction was already deferred."""
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=error)
        else:
            await interaction.response.send_message(content, ephemeral=error)

    # ----- commands --------------------------------------------------------

    @app_commands.command(
        name="play", description="Play a track, or add it to the queue."
    )
    @app_commands.describe(query="A search term or a URL (YouTube, SoundCloud, …).")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()

        player = await self._get_player(interaction, connect=True)
        if player is None:
            return

        # Remember where to announce tracks for this session.
        player.home = interaction.channel  # type: ignore[attr-defined]

        try:
            results: wavelink.Search = await wavelink.Playable.search(query)
        except Exception:  # noqa: BLE001
            log.exception("Search failed for query: %s", query)
            await self._respond(interaction, "Search failed. Try again.", error=True)
            return

        if not results:
            await self._respond(
                interaction, f"No results found for **{query}**.", error=True
            )
            return

        if isinstance(results, wavelink.Playlist):
            added = await player.queue.put_wait(results)
            await interaction.followup.send(
                embed=audio.playlist_queued_embed(results, added)
            )
        else:
            track = results[0]
            await player.queue.put_wait(track)
            await interaction.followup.send(
                embed=audio.track_queued_embed(track, position=player.queue.count)
            )

        if not player.playing:
            await player.play(player.queue.get())

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or not player.playing:
            await self._respond(interaction, "Nothing is playing.", error=True)
            return
        await player.skip(force=True)
        await self._respond(interaction, "⏭️ Skipped.")

    @app_commands.command(name="pause", description="Pause playback.")
    async def pause(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or not player.playing:
            await self._respond(interaction, "Nothing is playing.", error=True)
            return
        if player.paused:
            await self._respond(interaction, "Already paused.", error=True)
            return
        await player.pause(True)
        await self._respond(interaction, "⏸️ Paused.")

    @app_commands.command(name="resume", description="Resume playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None:
            await self._respond(interaction, "I'm not connected.", error=True)
            return
        if not player.paused:
            await self._respond(interaction, "Playback isn't paused.", error=True)
            return
        await player.pause(False)
        await self._respond(interaction, "▶️ Resumed.")

    @app_commands.command(
        name="stop", description="Stop playback and clear the queue."
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None:
            await self._respond(interaction, "I'm not connected.", error=True)
            return
        player.queue.clear()
        await player.stop()
        await self._respond(interaction, "⏹️ Stopped and cleared the queue.")

    @app_commands.command(name="leave", description="Disconnect from voice.")
    async def leave(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None:
            await self._respond(interaction, "I'm not connected.", error=True)
            return
        await player.disconnect()
        await self._respond(interaction, "👋 Disconnected.")

    @app_commands.command(name="queue", description="Show the current queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or (player.current is None and player.queue.is_empty):
            await self._respond(interaction, "The queue is empty.", error=True)
            return
        await interaction.response.send_message(embed=audio.queue_embed(player))

    @app_commands.command(
        name="nowplaying", description="Show the currently playing track."
    )
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or player.current is None:
            await self._respond(interaction, "Nothing is playing.", error=True)
            return
        await interaction.response.send_message(embed=audio.now_playing_embed(player))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
