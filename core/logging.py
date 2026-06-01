"""Central logging configuration.

A single place to configure formatting and levels so every module logs
consistently. Logs go to stdout, which is what Docker/Portainer capture.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="[{asctime}] [{levelname:<8}] {name}: {message}",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="{",
        )
    )

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)

    # These libraries are noisy at INFO; keep them quieter unless we're debugging.
    logging.getLogger("discord").setLevel(
        logging.DEBUG if log_level <= logging.DEBUG else logging.WARNING
    )
    logging.getLogger("wavelink").setLevel(log_level)
