"""Central configuration loaded from environment variables.

Values are read once at import time. For local development they come from a
`.env` file (via python-dotenv); in Docker/Portainer they come from the
container environment, which always takes precedence over `.env`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env if present. By design this does NOT override variables already set
# in the real environment (e.g. those injected by docker-compose / Portainer).
load_dotenv(override=False)


def _get_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.isdigit() else None


# --- Discord ---
DISCORD_TOKEN: str | None = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID: int | None = _get_optional_int("DEV_GUILD_ID")

# --- Lavalink ---
LAVALINK_URI: str = os.getenv("LAVALINK_URI", "http://localhost:2333")
LAVALINK_PASSWORD: str = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

# --- Misc ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def validate() -> None:
    """Raise a clear error if required configuration is missing.

    Called by the entrypoint before the bot starts so misconfiguration fails
    fast with an actionable message instead of a cryptic library error.
    """
    missing: list[str] = []
    if not DISCORD_TOKEN:
        missing.append("DISCORD_TOKEN")
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill it in (or set them in your "
            "container environment)."
        )
