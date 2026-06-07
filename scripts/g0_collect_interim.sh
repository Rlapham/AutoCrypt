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
  # GRADUATION-AWARE collection (the M3-session / phase-G1 fix). The earlier design saturated
  # the watchlist on tick 1 and froze it for max-pool-age, so the later-created AMM pool of a
  # graduating token never won a slot (census: 2/185 post-grad coverage). Now:
  #   --grad-reserved 30 keeps 30 of 60 slots open for graduation pools (an AMM pool for a
  #     mint already seen on a bonding curve); they are PINNED (never locked out) and
  #   --max-pool-age-h 168 holds each graduation for its full multi-day accumulator arc, while
  #   --discovery-age-h 6 ages out non-graduation discovery pools fast so the watchlist never
  #     freezes and graduation headroom stays open.
  # PoolCreated is still written for ALL enumerated pools (survivorship intact).
  /usr/local/bin/uv run autocrypt collect \
    --interval 90 \
    --iterations 0 \
    --enum-pages 3 \
    --watch-max 60 \
    --grad-reserved 30 \
    --max-pool-age-h 168 \
    --discovery-age-h 6 \
    --tx-pages 2
  code=$?
  echo "[g0-interim] collector exited code=$code at $(date) — restarting in ${backoff}s" >&2
  sleep "$backoff"
  # gentle exponential backoff, capped at 5 min, so a sustained outage doesn't hot-loop
  backoff=$(( backoff * 2 ))
  [ "$backoff" -gt 300 ] && backoff=300
done
