"""Music module: slash commands for voice playback via Lavalink/wavelink.

Each Discord server (guild) gets its own player and queue automatically —
wavelink keys players by guild, so state never leaks between servers.
"""

from __future__ import annotations

import logging
import time

import discord
import wavelink
from discord import app_commands
from discord.ext import commands, tasks

from cogs.components import NowPlayingControls
from services import audio

log = logging.getLogger("music")


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self._progress_updater.start()

    async def cog_unload(self) -> None:
        self._progress_updater.cancel()

    # ----- background tasks ------------------------------------------------

    @tasks.loop(seconds=audio.NOW_PLAYING_REFRESH)
    async def _progress_updater(self) -> None:
        """Advance each active now-playing progress bar by editing its message.

        Discord embeds don't animate, so the bar only moves when we re-render
        it. To keep edits (and the thumbnail flicker they cause) minimal, we
        only edit when the bar has actually moved a slot.
        """
        for vc in list(self.bot.voice_clients):
            if not isinstance(vc, wavelink.Player):
                continue
            player = vc
            message: discord.Message | None = getattr(player, "np_message", None)
            track = player.current
            if message is None or track is None or player.paused or track.is_stream:
                continue
            if time.monotonic() < getattr(player, "seek_until", 0.0):
                continue  # a manual seek is still settling; don't render stale pos
            fill = audio.progress_fill(player.position, track.length)
            if getattr(player, "np_fill", None) == fill:
                continue
            player.np_fill = fill  # type: ignore[attr-defined]
            try:
                await message.edit(embed=audio.now_playing_embed(player))
            except discord.HTTPException:
                pass

    @_progress_updater.before_loop
    async def _before_progress_updater(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_np(
        self, player: wavelink.Player, *, position: int | None = None
    ) -> None:
        """Re-render the now-playing panel so its embed and buttons reflect a
        change made outside the periodic updater (pause, volume, loop, seek …).

        ``position`` (ms) optimistically overrides the playhead after a seek.
        """
        message: discord.Message | None = getattr(player, "np_message", None)
        if message is None or player.current is None:
            return
        view: NowPlayingControls | None = getattr(player, "np_view", None)
        kwargs: dict = {"embed": audio.now_playing_embed(player, position=position)}
        if view is not None:
            view.sync(player)
            kwargs["view"] = view
        try:
            await message.edit(**kwargs)
        except discord.HTTPException:
            pass

    async def _retire_panel(self, player: wavelink.Player) -> None:
        """Deactivate the previous now-playing panel (stop its view, drop its
        buttons) so only the newest panel stays interactive."""
        old_view: NowPlayingControls | None = getattr(player, "np_view", None)
        if old_view is not None:
            old_view.stop()
        old_message: discord.Message | None = getattr(player, "np_message", None)
        if old_message is not None:
            try:
                await old_message.edit(view=None)
            except discord.HTTPException:
                pass

    def _set_panel(
        self,
        player: wavelink.Player,
        message: discord.Message,
        view: NowPlayingControls,
    ) -> None:
        """Record a freshly-posted panel as the live one for this player."""
        player.np_message = message  # type: ignore[attr-defined]
        player.np_view = view  # type: ignore[attr-defined]
        track = player.current
        player.np_fill = (  # type: ignore[attr-defined]
            audio.progress_fill(player.position, track.length)
            if track is not None and not track.is_stream
            else None
        )

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
        """Announce the track (with controls) where /play was used."""
        player = payload.player
        if player is None:
            return
        home: discord.abc.Messageable | None = getattr(player, "home", None)
        if home is None:
            return

        await self._retire_panel(player)
        view = NowPlayingControls()
        view.sync(player)
        try:
            message = await home.send(embed=audio.now_playing_embed(player), view=view)
        except discord.HTTPException:
            return
        self._set_panel(player, message, view)

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
        await self._refresh_np(player)
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
        await self._refresh_np(player)
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
        # Retire the old panel and make this fresh message the live one, so its
        # progress bar keeps updating and its buttons reflect state.
        await self._retire_panel(player)
        view = NowPlayingControls()
        view.sync(player)
        await interaction.response.send_message(
            embed=audio.now_playing_embed(player), view=view
        )
        message = await interaction.original_response()
        self._set_panel(player, message, view)

    @app_commands.command(
        name="volume", description="Show or set the playback volume (0-200)."
    )
    @app_commands.describe(level="New volume 0-200; omit to show the current volume.")
    async def volume(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 0, audio.MAX_VOLUME] | None = None,
    ) -> None:
        player = await self._get_player(interaction)
        if player is None:
            await self._respond(interaction, "I'm not connected.", error=True)
            return
        if level is None:
            await self._respond(interaction, f"🔊 Volume is **{player.volume}%**.")
            return
        await player.set_volume(level)
        await self._refresh_np(player)
        await self._respond(interaction, f"🔊 Volume set to **{level}%**.")

    @app_commands.command(
        name="loop", description="Loop the current track, the whole queue, or turn it off."
    )
    @app_commands.describe(mode="What to repeat.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Current track", value="track"),
            app_commands.Choice(name="Whole queue", value="queue"),
        ]
    )
    async def loop(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        player = await self._get_player(interaction)
        if player is None:
            await self._respond(interaction, "I'm not connected.", error=True)
            return
        player.queue.mode = {
            "off": wavelink.QueueMode.normal,
            "track": wavelink.QueueMode.loop,
            "queue": wavelink.QueueMode.loop_all,
        }[mode.value]
        await self._refresh_np(player)
        await self._respond(interaction, f"🔁 Loop set to **{mode.name}**.")

    @app_commands.command(name="shuffle", description="Shuffle the upcoming queue.")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or player.queue.count < 2:
            await self._respond(
                interaction, "Need at least 2 queued tracks to shuffle.", error=True
            )
            return
        player.queue.shuffle()
        await self._respond(interaction, f"🔀 Shuffled **{player.queue.count}** tracks.")

    @app_commands.command(
        name="seek", description="Jump to a position in the current track (e.g. 1:30)."
    )
    @app_commands.describe(position="A timestamp: seconds, M:SS, or H:MM:SS.")
    async def seek(self, interaction: discord.Interaction, position: str) -> None:
        player = await self._get_player(interaction)
        if player is None or player.current is None:
            await self._respond(interaction, "Nothing is playing.", error=True)
            return
        track = player.current
        if track.is_stream or not getattr(track, "is_seekable", True):
            await self._respond(interaction, "This track can't be seeked.", error=True)
            return
        ms = audio.parse_timestamp(position)
        if ms is None:
            await self._respond(
                interaction,
                "Invalid time. Use seconds or `M:SS` (e.g. `1:30`).",
                error=True,
            )
            return
        ms = max(0, min(ms, track.length))
        await player.seek(ms)
        audio.mark_seek(player, ms)
        await self._refresh_np(player, position=ms)
        await self._respond(interaction, f"⏩ Seeked to `{audio.format_duration(ms)}`.")

    @app_commands.command(
        name="remove", description="Remove a track from the queue by its position."
    )
    @app_commands.describe(index="Queue position to remove (see /queue).")
    async def remove(
        self, interaction: discord.Interaction, index: app_commands.Range[int, 1, None]
    ) -> None:
        player = await self._get_player(interaction)
        if player is None or player.queue.is_empty:
            await self._respond(interaction, "The queue is empty.", error=True)
            return
        if index > player.queue.count:
            await self._respond(
                interaction,
                f"There are only {player.queue.count} track(s) in the queue.",
                error=True,
            )
            return
        track = player.queue[index - 1]
        del player.queue[index - 1]
        await self._respond(interaction, f"🗑️ Removed **{track.title}**.")

    @app_commands.command(
        name="clear", description="Clear the upcoming queue (keeps the current track)."
    )
    async def clear(self, interaction: discord.Interaction) -> None:
        player = await self._get_player(interaction)
        if player is None or player.queue.is_empty:
            await self._respond(interaction, "The queue is already empty.", error=True)
            return
        count = player.queue.count
        player.queue.clear()
        await self._respond(
            interaction, f"🧹 Cleared **{count}** track(s) from the queue."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
