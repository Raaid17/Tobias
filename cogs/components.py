"""Interactive message components for the music module.

This is a UI helper imported by `cogs/music.py` — *not* a bot extension, so it
has no `setup()` and isn't listed in `INITIAL_COGS`. Views belong in the cog
layer (not `services/`) because they act on a live Discord interaction.

The controls operate on the guild's current player, fetched fresh on every
click, so a single panel keeps working as tracks change. Buttons are guarded:
only members in the bot's voice channel may use them. Call `sync(player)`
before (re)rendering so the play/pause and loop buttons reflect live state.

Layout:
    row 0 (transport):  ⏪  ⏯  ⏩  ⏭  ⏹
    row 1 (modes):      🔀  🔁

The progress bar in the embed is display-only — Discord has no draggable
slider component — so ⏪/⏩ (and the /seek command) are how you scrub.

Note: these views are not persistent across bot restarts (no `custom_id` /
`add_view` registration). After a restart, run `/nowplaying` for a fresh panel.
"""

from __future__ import annotations

import time

import discord
import wavelink

from services import audio


class NowPlayingControls(discord.ui.View):
    """Playback controls attached to a "Now playing" message."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    def sync(self, player: wavelink.Player) -> None:
        """Reflect live player state on the stateful buttons.

        Must be called before the message is (re)rendered with this view.
        """
        self.play_pause.emoji = "▶️" if player.paused else "⏸️"

        mode = player.queue.mode
        if mode is wavelink.QueueMode.loop:
            self.loop.emoji = "🔂"  # repeat-one
            self.loop.style = discord.ButtonStyle.success
        elif mode is wavelink.QueueMode.loop_all:
            self.loop.emoji = "🔁"
            self.loop.style = discord.ButtonStyle.success
        else:
            self.loop.emoji = "🔁"
            self.loop.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Allow only members in the bot's voice channel to use the controls."""
        player: wavelink.Player | None = (
            interaction.guild.voice_client if interaction.guild else None  # type: ignore[assignment]
        )
        if player is None or player.channel is None:
            await interaction.response.send_message(
                "I'm not connected to a voice channel.", ephemeral=True
            )
            return False

        user = interaction.user
        if (
            not isinstance(user, discord.Member)
            or user.voice is None
            or user.voice.channel != player.channel
        ):
            await interaction.response.send_message(
                "Join my voice channel to use these controls.", ephemeral=True
            )
            return False
        return True

    @staticmethod
    def _player(interaction: discord.Interaction) -> wavelink.Player:
        # Safe: interaction_check guarantees a connected player.
        return interaction.guild.voice_client  # type: ignore[return-value]

    async def _do_seek(self, interaction: discord.Interaction, *, forward: bool) -> None:
        player = self._player(interaction)
        track = player.current
        if track is None:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return
        if track.is_stream or not getattr(track, "is_seekable", True):
            await interaction.response.send_message(
                "This track can't be seeked.", ephemeral=True
            )
            return
        # While a recent seek is still settling, accumulate off the last target
        # so rapid ⏪/⏩ presses add up; otherwise base off the live position.
        if time.monotonic() < getattr(player, "seek_until", 0.0):
            base = getattr(player, "seek_target", player.position)
        else:
            base = player.position
        step = audio.SEEK_STEP_MS if forward else -audio.SEEK_STEP_MS
        target = max(0, min(base + step, track.length))
        await player.seek(target)
        audio.mark_seek(player, target)
        await interaction.response.edit_message(
            embed=audio.now_playing_embed(player, position=target), view=self
        )

    # ----- row 0: transport ------------------------------------------------

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary, row=0)
    async def rewind(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._do_seek(interaction, forward=False)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, row=0)
    async def play_pause(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        player = self._player(interaction)
        await player.pause(not player.paused)
        self.sync(player)
        await interaction.response.edit_message(
            embed=audio.now_playing_embed(player), view=self
        )

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, row=0)
    async def forward(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._do_seek(interaction, forward=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        player = self._player(interaction)
        if not player.playing:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )
            return
        await player.skip(force=True)
        await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_playback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Named stop_playback (not stop) so it doesn't shadow View.stop().
        player = self._player(interaction)
        player.queue.clear()
        await player.stop()
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        self.stop()  # stop listening for further interactions on this view
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "⏹️ Stopped and cleared the queue.", ephemeral=True
        )

    # ----- row 1: modes ----------------------------------------------------

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        player = self._player(interaction)
        if player.queue.count < 2:
            await interaction.response.send_message(
                "Need at least 2 queued tracks to shuffle.", ephemeral=True
            )
            return
        player.queue.shuffle()
        await interaction.response.send_message(
            f"🔀 Shuffled {player.queue.count} tracks.", ephemeral=True
        )

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        player = self._player(interaction)
        # Cycle Off -> Track -> Queue -> Off.
        nxt = {
            wavelink.QueueMode.normal: wavelink.QueueMode.loop,
            wavelink.QueueMode.loop: wavelink.QueueMode.loop_all,
            wavelink.QueueMode.loop_all: wavelink.QueueMode.normal,
        }
        player.queue.mode = nxt.get(player.queue.mode, wavelink.QueueMode.normal)
        self.sync(player)
        if player.current is not None:
            await interaction.response.edit_message(
                embed=audio.now_playing_embed(player), view=self
            )
        else:
            await interaction.response.edit_message(view=self)
