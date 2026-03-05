"""CLI entry point: python -m ha_agent [--config path/to/config.yaml]"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ha-sentinel",
        description="HA-SentinelAI — Autonomous high-availability monitoring agent",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to YAML config file (default: ha_config.yaml or HA_SENTINEL_CONFIG_PATH env)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate config and exit without starting the agent",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )

    args = parser.parse_args()

    if args.version:
        from ha_agent import __agent_name__, __version__
        print(f"{__agent_name__} v{__version__}")
        sys.exit(0)

    from ha_agent.config import load_config

    if args.validate:
        cfg = load_config(args.config)
        print(f"Config loaded: {len(cfg.targets)} targets, {len(cfg.notification_channels)} notification channels")
        for t in cfg.targets:
            status = "enabled" if t.enabled else "disabled"
            print(f"  [{status}] {t.name} ({t.probe_type.value}) -> {t.endpoint}")
        print("Config is valid.")
        sys.exit(0)

    from ha_agent.agent import run_agent
    run_agent(config_path=args.config)


if __name__ == "__main__":
    main()
