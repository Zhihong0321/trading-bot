"""Logging utilities."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_directory: str) -> None:
    """Initialise a rotating log file handler."""

    Path(log_directory).mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(Path(log_directory) / "bot.log")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)


__all__ = ["configure_logging"]
