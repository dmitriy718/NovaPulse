"""
Secrets loader — reads raw secrets from a mounted file into os.environ.

Docker Compose interpolates $VAR in both .env AND env_file: entries, which
mangles bcrypt hashes and other values containing $.  This module bypasses
Docker's interpolation entirely by reading secrets from a plain file mounted
via a Docker volume (.secrets/env → /app/.secrets/env).

Usage:
    import src.utils.secrets  # auto-loads on import (before other modules)

The secrets file format is standard KEY=VALUE, one per line.  Lines starting
with # are comments.  No $$ escaping needed — values are read raw.

Load order (first found wins):
    1. /app/.secrets/env     (inside Docker container)
    2. .secrets/env           (local dev / host)

If the file doesn't exist, this module is a silent no-op.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SEARCH_PATHS = [
    Path("/app/.secrets/env"),
    Path(".secrets/env"),
]


def _load_secrets_file(path: Path) -> int:
    """Parse a KEY=VALUE file and inject into os.environ. Returns count loaded."""
    loaded = 0
    with open(path) as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            eq = line.find("=")
            if eq < 1:
                continue
            key = line[:eq].strip()
            val = line[eq + 1:]  # preserve leading/trailing spaces in value
            # Only set if not already in environ (explicit env wins over file)
            if key not in os.environ or not os.environ[key]:
                os.environ[key] = val
                loaded += 1
    return loaded


def load() -> None:
    """Find and load the first available secrets file."""
    for path in _SEARCH_PATHS:
        if path.is_file():
            try:
                count = _load_secrets_file(path)
                if count:
                    logger.info("Loaded %d secret(s) from %s", count, path)
                return
            except Exception as exc:
                logger.warning("Failed to read secrets from %s: %s", path, exc)
    # No secrets file found — perfectly fine for dev/CI environments.


# Auto-load on import so secrets are available before any other module reads env.
load()
