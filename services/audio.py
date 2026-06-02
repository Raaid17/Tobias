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
# Highest volume /volume will accept. 100 is unity gain; above that amplifies
# and can distort, so we cap it rather than allow Lavalink's full 0-1000.
MAX_VOLUME: int = 200
# Seconds with nothing playing before the bot leaves the voice channel.
INACTIVE_TIMEOUT: int = 120

EMBED_COLOR = discord.Color.blurple()
# How many upcoming tracks to list in /queue.
QUEUE_PREVIEW_LEN = 10
# Width (in characters) of the now-playing progress bar.
PROGRESS_BAR_SLOTS = 18


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


def loop_mode_label(mode: wavelink.QueueMode) -> str:
    """Human-readable name for a queue loop mode."""
    return {
        wavelink.QueueMode.normal: "Off",
        wavelink.QueueMode.loop: "Track",
        wavelink.QueueMode.loop_all: "Queue",
    }.get(mode, "Off")


def parse_timestamp(value: str) -> int | None:
    """Parse a user timestamp into milliseconds, or None if it's malformed.

    Accepts plain seconds ("90"), "M:SS" ("1:30"), or "H:MM:SS" ("1:02:03").
    """
    parts = value.strip().split(":")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return None
    if not numbers or any(n < 0 for n in numbers):
        return None
    if len(numbers) == 1:
        seconds = numbers[0]
    elif len(numbers) == 2:
        seconds = numbers[0] * 60 + numbers[1]
    elif len(numbers) == 3:
        seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        return None
    return seconds * 1000


def _progress_bar(position: int, length: int, slots: int = PROGRESS_BAR_SLOTS) -> str:
    """A textual playback progress bar, e.g. ▬▬▬🔘▬▬▬▬▬."""
    if length <= 0:
        return ""
    filled = int(slots * min(position, length) / length)
    filled = max(0, min(filled, slots - 1))
    return "▬" * filled + "🔘" + "▬" * (slots - filled - 1)


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

    embed = discord.Embed(
        title="Now playing",
        description=f"[{track.title}]({track.uri})",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Artist", value=track.author or "Unknown", inline=True)

    if track.is_stream:
        embed.add_field(name="Duration", value="🔴 LIVE", inline=True)
    else:
        bar = _progress_bar(player.position, track.length)
        elapsed = format_duration(player.position)
        total = format_duration(track.length)
        embed.add_field(
            name="Progress",
            value=f"{bar}\n`{elapsed} / {total}`",
            inline=False,
        )

    if track.artwork:
        embed.set_thumbnail(url=track.artwork)

    state = "⏸️ Paused" if player.paused else "▶️ Playing"
    embed.set_footer(
        text=(
            f"{state}  ·  Volume {player.volume}%  ·  "
            f"Loop: {loop_mode_label(player.queue.mode)}"
        )
    )
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

    loop_label = loop_mode_label(player.queue.mode)
    upcoming = list(player.queue)
    if not upcoming:
        embed.add_field(name="Up next", value="*(empty)*", inline=False)
        embed.set_footer(text=f"Loop: {loop_label}")
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

    total_ms = sum(t.length for t in upcoming if not t.is_stream)
    footer = f"{len(upcoming)} track(s)"
    if total_ms > 0:
        footer += f"  ·  {format_duration(total_ms)} total"
    footer += f"  ·  Loop: {loop_label}"
    embed.set_footer(text=footer)
    return embed
