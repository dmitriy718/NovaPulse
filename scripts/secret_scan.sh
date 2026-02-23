#!/usr/bin/env bash
set -euo pipefail

# Lightweight secret scan helper. Requires `gitleaks` on PATH.
# Usage: scripts/secret_scan.sh [path]

TARGET="${1:-.}"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "gitleaks not found. Install from https://gitleaks.io or brew install gitleaks." >&2
  exit 127
fi

gitleaks detect --source "$TARGET" --redact
