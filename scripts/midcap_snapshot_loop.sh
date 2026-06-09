#!/bin/bash
# Track M forward universe snapshot loop — accrues a CLEAN, survivorship-safe mid-cap
# set over wall-clock (records all enumerated pools daily with in_band flagged, so a
# pool captured while alive remains after it later dies/delists).
#
# Interim durability ONLY (like the G0 collector): a nohup process survives this session
# but NOT reboot. The reboot-durable form is the launchd agent, currently blocked by
# macOS TCC on ~/Documents (grant Full Disk Access to uv, or relocate the repo). See
# docs/phase-M1-synthesis.md.
#
# Sleeps FIRST so the next snapshot lands ~24h out (snapshot #1 was already taken at M1
# build time) and to let the GeckoTerminal rate limiter cool down.

set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"
# Self-locating: derive repo root from this script's own path so a repo move
# (e.g. out of ~/Documents to dodge macOS TCC) doesn't silently break the agent.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export DB_URL="duckdb:///${REPO}/data/autocrypt_midcap.duckdb"

while true; do
  sleep 86400
  /usr/local/bin/uv run autocrypt midcap-snapshot || echo "snapshot failed $(date)"
done
