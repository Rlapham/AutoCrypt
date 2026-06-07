#!/bin/bash
# G0 — INTERIM resilient forward collector for the Track G graduation/accumulator cohort.
#
# Interim durability only (nohup; survives this session but NOT reboot — the durable
# form is the launchd agent com.autocrypt.collector, blocked by macOS TCC on ~/Documents).
#
# Unlike scripts/g0_collect.sh (which `exec`s a single `uv run` under `set -e`, so any
# transient network error — e.g. a DNS ConnectError — kills it permanently), this wrapper
# RESTARTS the collector after a crash. That is exactly how the previous G0 process died:
# a `ConnectError: nodename nor servname provided` with no restart loop. Backoff is capped.
#
# Writes to the dedicated graduation-cohort store (separate file from autocrypt_midcap.duckdb,
# so it never contends with the Track-M snapshot loop's single-writer window).

export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"
REPO="/Users/richardlapham/Documents/Git/AutoCrypt"
cd "$REPO" || exit 1
export DB_URL="duckdb:///${REPO}/data/autocrypt_graduation.duckdb"

backoff=15
while true; do
  # --amm-reserved keeps half the watchlist open for AMM (graduation-target) pools so the
  # post-graduation accumulator arc is actually tailed (G0 census showed 0/176 coverage
  # before this fix). PoolCreated is still written for ALL pools (survivorship intact).
  /usr/local/bin/uv run autocrypt collect \
    --interval 90 \
    --iterations 0 \
    --enum-pages 3 \
    --watch-max 60 \
    --amm-reserved 30 \
    --max-pool-age-h 168 \
    --tx-pages 2
  code=$?
  echo "[g0-interim] collector exited code=$code at $(date) — restarting in ${backoff}s" >&2
  sleep "$backoff"
  # gentle exponential backoff, capped at 5 min, so a sustained outage doesn't hot-loop
  backoff=$(( backoff * 2 ))
  [ "$backoff" -gt 300 ] && backoff=300
done
