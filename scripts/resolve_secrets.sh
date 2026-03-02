#!/usr/bin/env bash
# ==============================================================================
# resolve_secrets.sh — Resolve 1Password op:// references into .secrets/env
#
# Reads a template file (.env.secrets.tpl) where values are op:// references,
# resolves each via `op read`, and writes a plain .secrets/env file.
#
# The Python app reads .secrets/env at startup (src/utils/secrets.py) BEFORE
# any other module touches os.environ.  This completely bypasses Docker
# Compose's $VAR interpolation, which mangles bcrypt hashes and other
# values containing $ signs.
#
# Usage:
#   ./scripts/resolve_secrets.sh                        # defaults
#   ./scripts/resolve_secrets.sh my.tpl .secrets/env    # custom paths
#   FORCE=1 ./scripts/resolve_secrets.sh                # overwrite existing
#
# Requires: 1Password CLI (`op`) authenticated (op signin / service account)
# ==============================================================================
set -euo pipefail

TPL="${1:-.env.secrets.tpl}"
OUT="${2:-.secrets/env}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

die() { echo -e "${RED}ERROR: $*${NC}" >&2; exit 1; }

# --- Pre-checks ---
[ -f "$TPL" ] || die "Template not found: $TPL"

if [ -f "$OUT" ] && [ "${FORCE:-}" != "1" ]; then
    echo -e "${YELLOW}$OUT already exists. Set FORCE=1 to overwrite, or delete it first.${NC}"
    exit 0
fi

if ! command -v op &>/dev/null; then
    die "1Password CLI (op) not found. Install: https://developer.1password.com/docs/cli/get-started/"
fi

# Quick auth check — op read a known ref or whoami
if ! op whoami &>/dev/null 2>&1; then
    die "1Password CLI not authenticated. Run 'op signin' or set OP_SERVICE_ACCOUNT_TOKEN."
fi

# --- Resolve ---
resolved=0
failed=0
tmp="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

while IFS= read -r line || [[ -n "$line" ]]; do
    # Preserve comments and blank lines
    if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "${line// /}" ]]; then
        echo "$line" >> "$tmp"
        continue
    fi

    # Split on first '='
    key="${line%%=*}"
    val="${line#*=}"

    if [[ "$val" == op://* ]]; then
        echo -ne "${DIM}  Resolving ${key}...${NC} "
        if secret="$(op read "$val" 2>/dev/null)"; then
            echo "${key}=${secret}" >> "$tmp"
            echo -e "${GREEN}OK${NC}"
            resolved=$((resolved + 1))
        else
            echo -e "${RED}FAILED${NC}"
            echo "${key}=" >> "$tmp"
            failed=$((failed + 1))
        fi
    else
        # Pass through non-op:// values as-is
        echo "$line" >> "$tmp"
    fi
done < "$TPL"

# Atomic move
mv "$tmp" "$OUT"
chmod 600 "$OUT"
trap - EXIT

echo ""
echo -e "${GREEN}Resolved ${resolved} secret(s) into ${OUT}${NC}"
if [ "$failed" -gt 0 ]; then
    echo -e "${RED}Failed to resolve ${failed} secret(s) — check 1Password vault access.${NC}"
    exit 1
fi
