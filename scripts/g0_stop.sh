#!/bin/bash
# G0 — FULL STOP for the Track-G forward collector.
#
# Because the collector runs under a launchd LaunchAgent with KeepAlive=true, a plain
# `kill` does NOT stop it — launchd immediately respawns it. This script tears it down
# COMPLETELY and durably so it stays dead until you deliberately bring it back:
#
#   1. `bootout`  — unloads the agent from the current GUI domain (stops it now and
#                   disarms KeepAlive so it will not respawn this session).
#   2. `disable`  — marks it disabled so it will NOT auto-start at the next login/boot
#                   either (RunAtLoad is overridden by the disabled flag).
#   3. kill strays — reaps any orphaned `caffeinate`/`autocrypt collect` processes so
#                    the machine is free to sleep again and the DuckDB write-lock frees.
#
# Use this when the Track-G dataset has ripened (or any time you want collection OFF).
# To bring it back later:
#   launchctl enable  "gui/$(id -u)/com.autocrypt.collector"
#   launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.autocrypt.collector.plist
# (or simply log out and back in, once re-enabled).

set -uo pipefail

LABEL="com.autocrypt.collector"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo "Stopping ${LABEL} ..."

# 1) Unload (stops now + disarms KeepAlive). Tolerate "not loaded".
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null \
  && echo "  bootout: agent unloaded" \
  || echo "  bootout: agent was not loaded (ok)"

# 2) Persistently disable so it does not come back at next login/boot.
launchctl disable "${DOMAIN}/${LABEL}" 2>/dev/null \
  && echo "  disable: agent disabled (won't auto-start at login)" \
  || echo "  disable: could not disable (may already be disabled)"

# 3) Reap any stray processes (the caffeinate wrapper + the python collector).
#    pkill returns non-zero when nothing matched — that's fine.
pkill -f "caffeinate -ims .*autocrypt collect" 2>/dev/null && echo "  killed stray caffeinate wrapper(s)"
pkill -f "autocrypt collect"                   2>/dev/null && echo "  killed stray collector process(es)"

# 4) Verify nothing is left holding the DB lock.
sleep 1
if pgrep -f "autocrypt collect" >/dev/null 2>&1; then
  echo "WARNING: a collector process is still running:"
  pgrep -fl "autocrypt collect"
  echo "  (re-run this script, or kill the PID above manually)"
  exit 1
fi

echo "Done — collector fully stopped and disabled. (plist left in place at ${PLIST})"
