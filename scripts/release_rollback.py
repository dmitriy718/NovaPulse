#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _resolve_snapshot_id(base_dir: Path, snapshot_id: str, latest: bool) -> str:
    if snapshot_id:
        return snapshot_id
    if latest:
        latest_file = base_dir.parent / "latest_snapshot.txt"
        if latest_file.exists():
            return latest_file.read_text(encoding="utf-8").strip()
    raise ValueError("Provide --snapshot-id or use --latest.")


def rollback_config(
    snapshots_dir: Path,
    snapshot_id: str,
    config_path: Path,
    backups_dir: Path,
) -> Path:
    snapshot_path = snapshots_dir / snapshot_id / "config" / "config.yaml"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot config not found: {snapshot_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"Current config not found: {config_path}")

    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-pre-rollback.yaml")
    backup_path = backups_dir / backup_name
    shutil.copy2(config_path, backup_path)
    shutil.copy2(snapshot_path, config_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rollback NovaPulse config to a previously created release snapshot.",
    )
    parser.add_argument("--snapshots-dir", default=".release/snapshots")
    parser.add_argument("--snapshot-id", default="")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--config-path", default="config/config.yaml")
    parser.add_argument("--backups-dir", default=".release/backups")
    args = parser.parse_args()

    snapshots_dir = Path(args.snapshots_dir)
    snapshot_id = _resolve_snapshot_id(snapshots_dir, args.snapshot_id.strip(), args.latest)
    backup_path = rollback_config(
        snapshots_dir=snapshots_dir,
        snapshot_id=snapshot_id,
        config_path=Path(args.config_path),
        backups_dir=Path(args.backups_dir),
    )

    print(f"rolled_back_to={snapshot_id}")
    print(f"backup_path={backup_path}")


if __name__ == "__main__":
    main()
