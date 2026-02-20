#!/usr/bin/env python3
"""
NovaPulse VPS Watchdog

Polls the operator heartbeat endpoint and optionally auto-restarts the stack
after repeated degraded checks. Intended for unattended VPS operation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict


def _http_get_json(url: str, api_key: str, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _restart_stack(compose_dir: str) -> None:
    subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=compose_dir,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="NovaPulse VPS watchdog")
    parser.add_argument("--url", default=os.getenv("WATCHDOG_URL", "http://127.0.0.1:8090/api/v1/ops/heartbeat"))
    parser.add_argument("--api-key", default=os.getenv("DASHBOARD_READ_KEY", ""))
    parser.add_argument("--interval", type=int, default=int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "30")))
    parser.add_argument("--degraded-threshold", type=int, default=int(os.getenv("WATCHDOG_DEGRADED_THRESHOLD", "4")))
    parser.add_argument("--compose-dir", default=os.getenv("WATCHDOG_COMPOSE_DIR", "."))
    parser.add_argument("--auto-restart", action="store_true", default=os.getenv("WATCHDOG_AUTO_RESTART", "1") not in ("0", "false", "False"))
    args = parser.parse_args()

    degraded_streak = 0
    while True:
        status = "degraded"
        try:
            payload = _http_get_json(args.url, args.api_key, timeout=8.0)
            status = str(payload.get("status", "degraded")).lower()
            print(f"[watchdog] status={status} degraded_streak={degraded_streak}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"[watchdog] heartbeat error: {e}")
            status = "degraded"
        except KeyboardInterrupt:
            return 0

        if status == "ok":
            degraded_streak = 0
        else:
            degraded_streak += 1
            if args.auto_restart and degraded_streak >= max(1, args.degraded_threshold):
                print("[watchdog] threshold reached -> restarting docker compose stack")
                _restart_stack(args.compose_dir)
                degraded_streak = 0

        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
