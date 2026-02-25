"""Structured logging setup for the HA agent."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", data_dir: str = "./data/ha_sentinel") -> None:
    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("ha_sentinel")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)

        file_handler = logging.handlers.RotatingFileHandler(
            str(log_dir / "ha_sentinel.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


import logging.handlers
