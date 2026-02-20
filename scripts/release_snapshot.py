#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git_info() -> tuple[str, str]:
    sha = "unknown"
    branch = "unknown"
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except Exception:
        pass
    return sha, branch


def create_snapshot(
    config_path: Path,
    out_dir: Path,
    label: str = "",
) -> Path:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    git_sha, branch = _git_info()
    suffix = f"-{label.strip()}" if label.strip() else ""
    snapshot_id = f"{ts}-{git_sha}{suffix}"
    snapshot_dir = out_dir / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    # Save config and key deployment manifests.
    config_dst = snapshot_dir / "config"
    config_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, config_dst / "config.yaml")

    for rel in (".env.example", "docker-compose.yml", "requirements.txt"):
        src = Path(rel)
        if src.exists():
            shutil.copy2(src, snapshot_dir / src.name)

    metadata = {
        "snapshot_id": snapshot_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "git_branch": branch,
        "config_path": str(config_path),
        "label": label.strip() or None,
    }
    (snapshot_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    latest_file = out_dir.parent / "latest_snapshot.txt"
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.write_text(snapshot_id + "\n", encoding="utf-8")
    return snapshot_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a versioned release snapshot for NovaPulse config.",
    )
    parser.add_argument("--config-path", default="config/config.yaml")
    parser.add_argument("--out-dir", default=".release/snapshots")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    snapshot_dir = create_snapshot(
        config_path=Path(args.config_path),
        out_dir=Path(args.out_dir),
        label=args.label,
    )
    print(f"snapshot_id={snapshot_dir.name}")
    print(f"snapshot_path={snapshot_dir}")


if __name__ == "__main__":
    main()
