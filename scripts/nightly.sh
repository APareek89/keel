#!/bin/bash
# Keel nightly pass. Deterministic half only — counts, promotes on threshold,
# flags drift, refreshes the Codex export and the map. No model, no tokens.
set -u
S="$HOME/.claude/skills/keel/scripts"
LOG="$HOME/brain/_index/nightly.log"
mkdir -p "$(dirname "$LOG")"
{
  echo "=== $(date '+%Y-%m-%d %H:%M') ==="
  python3 "$S/autobrain.py" absorb --days 45 --apply
  python3 "$S/autobrain.py" promote --days 45 --apply
  python3 "$S/autobrain.py" state  --days 90 --apply
  python3 "$S/autobrain.py" export-codex --days 14
  python3 "$S/brain.py" view --no-open
  echo
} >> "$LOG" 2>&1
# keep the log to the last 400 lines
tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
