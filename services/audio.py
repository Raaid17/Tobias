"""Audio service: reusable playback/presentation helpers.

This module holds music *domain* logic and presentation helpers that don't
depend on a specific Discord interaction. The cog (cogs/music.py) handles the
Discord-facing command flow and voice connection, then delegates here. Keeping
the split means the playback rules live in one testable place.
"""

from __future__ import annotations

import discord
import wavelink

# Defaults applied to every freshly-connected player.
DEFAULT_VOLUME: int = 60
# Seconds with nothing playing before the bot leaves the voice channel.
INACTIVE_TIMEOUT: int = 120

EMBED_COLOR = discord.Color.blurple()
# How many upcoming tracks to list in /queue.
QUEUE_PREVIEW_LEN = 10


def format_duration(milliseconds: int) -> str:
    """Render a track length (ms) as M:SS or H:MM:SS."""
    if milliseconds <= 0:
        return "0:00"
    total_seconds = milliseconds // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _track_length_label(track: wavelink.Playable) -> str:
    return "🔴 LIVE" if track.is_stream else format_duration(track.length)


def track_queued_embed(track: wavelink.Playable, position: int) -> discord.Embed:
    """Embed shown when a single track is added to the queue."""
    embed = discord.Embed(
        title="Added to queue",
        description=f"[{track.title}]({track.uri})",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Artist", value=track.author or "Unknown", inline=True)
    embed.add_field(name="Duration", value=_track_length_label(track), inline=True)
    embed.add_field(name="Position", value=f"#{position}", inline=True)
    if track.artwork:
        embed.set_thumbnail(url=track.artwork)
    return embed


def playlist_queued_embed(playlist: wavelink.Playlist, added: int) -> discord.Embed:
    embed = discord.Embed(
        title="Playlist added to queue",
        description=f"**{playlist.name}** — {added} track(s)",
        color=EMBED_COLOR,
    )
    if playlist.tracks and playlist.tracks[0].artwork:
        embed.set_thumbnail(url=playlist.tracks[0].artwork)
    return embed


def now_playing_embed(player: wavelink.Player) -> discord.Embed:
    """Embed describing the currently playing track."""
    track = player.current
    if track is None:
        return discord.Embed(
            title="Nothing is playing",
            color=EMBED_COLOR,
        )

    if track.is_stream:
        progress = "🔴 LIVE"
    else:
        progress = f"{format_duration(player.position)} / {format_duration(track.length)}"

    embed = discord.Embed(
        title="Now playing",
        description=f"[{track.title}]({track.uri})",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Artist", value=track.author or "Unknown", inline=True)
    embed.add_field(name="Duration", value=progress, inline=True)
    if track.artwork:
        embed.set_thumbnail(url=track.artwork)
    return embed


def queue_embed(player: wavelink.Player) -> discord.Embed:
    """Embed listing the current track and upcoming queue."""
    embed = discord.Embed(title="Queue", color=EMBED_COLOR)

    if player.current is not None:
        embed.add_field(
            name="Now playing",
            value=f"[{player.current.title}]({player.current.uri})",
            inline=False,
        )

    upcoming = list(player.queue)
    if not upcoming:
        embed.add_field(name="Up next", value="*(empty)*", inline=False)
        return embed

    lines = []
    for index, track in enumerate(upcoming[:QUEUE_PREVIEW_LEN], start=1):
        lines.append(
            f"`{index}.` [{track.title}]({track.uri}) "
            f"`{_track_length_label(track)}`"
        )
    remaining = len(upcoming) - QUEUE_PREVIEW_LEN
    if remaining > 0:
        lines.append(f"…and **{remaining}** more")

    embed.add_field(name="Up next", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"{len(upcoming)} track(s) in queue")
    return embed
