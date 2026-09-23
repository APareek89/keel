#!/bin/bash
# Push this checkout's skill into every client that has it installed.
#
# Claude Code and Codex each keep their own copy of the skill. They drift —
# that is how one client ends up running a 16-day-old SKILL.md that documents
# commands the scripts no longer have. Run this after every change.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Backups go OUTSIDE the skills directories. A copy left beside the skill is
# discovered as a second, duplicate skill by the client — same name, same
# description, offered to the model twice.
BKDIR="${KEEL_BACKUP_DIR:-$HOME/.keel-backups}"
mkdir -p "$BKDIR"

for DEST in "$HOME/.claude/skills/keel" "$HOME/.codex/skills/keel"; do
  [ -d "$DEST" ] || { echo "skip   $DEST (not installed)"; continue; }
  BK="$BKDIR/$(basename "$(dirname "$(dirname "$DEST")")")-keel.$(date +%Y%m%d%H%M%S)"
  cp -R "$DEST" "$BK"
  mkdir -p "$DEST/scripts"
  cp "$SRC/SKILL.md" "$DEST/SKILL.md"
  cp "$SRC/scripts"/*.py "$SRC/scripts"/*.sh "$DEST/scripts/"
  chmod +x "$DEST/scripts"/*.py "$DEST/scripts"/*.sh 2>/dev/null || true
  for extra in README.md LICENSE .gitignore; do
    [ -f "$SRC/$extra" ] && [ -e "$DEST/$extra" ] && cp "$SRC/$extra" "$DEST/$extra"
  done
  [ -d "$DEST/templates" ] && cp -R "$SRC/templates/." "$DEST/templates/"
  [ -d "$DEST/examples" ]  && cp -R "$SRC/examples/."  "$DEST/examples/"
  echo "synced $DEST   (backup: $BK)"
done

echo
echo "Codex has no session-start hook, so refresh its always-loaded surface:"
echo "  python3 $HOME/.claude/skills/keel/scripts/autobrain.py export-codex"
