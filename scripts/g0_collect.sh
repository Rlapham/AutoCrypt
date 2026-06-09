#!/bin/bash
# G0 — durable forward collector for the Track G graduation/accumulator cohort.
#
# Run under launchd (com.autocrypt.collector) so it survives reboot and restarts
# on crash — unlike the old `nohup` collector, which died and is not durable.
#
# It forward-collects a SURVIVORSHIP-COMPLETE swap dataset (selection by pool
# CREATION, never by survival) into a DEDICATED graduation-cohort DB, separate
# from the Iteration-1 store. Each admitted pool is tailed for a multi-DAY window
# (max_pool_age_h below) so the days-horizon "accumulator" arc — including any
# graduation milestone that occurs while it is watched — is captured point-in-time.
#
# Known limitation (revisit in G1): enumeration is by newest-pool creation, not
# graduation-filtered, and the watchlist is rate-limit-bounded, so per-week token
# breadth is modest. This is the free, immediate, survivorship-safe starting point;
# graduation-event detection + a graduation-filtered cohort are a later G-step,
# derivable from this raw multi-day store.

set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"
# Self-locating: derive repo root from this script's own path so a repo move
# (e.g. out of ~/Documents to dodge macOS TCC) doesn't silently break the agent.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Dedicated graduation-cohort store (kept separate from autocrypt.duckdb).
export DB_URL="duckdb:///${REPO}/data/autocrypt_graduation.duckdb"

# Multi-day hold so the days-horizon arc is captured; polite sampling cadence.
exec /usr/local/bin/uv run autocrypt collect \
  --interval 90 \
  --iterations 0 \
  --enum-pages 3 \
  --watch-max 60 \
  --max-pool-age-h 168 \
  --tx-pages 2
