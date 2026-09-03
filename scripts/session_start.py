#!/usr/bin/env python3
"""
SessionStart hook for the keel skill.

Loads ~/brain/profile.md and ~/brain/preferences/*.md into every session, so
output is aligned to how the user works without him having to re-brief anyone.

Emits the hook JSON envelope on stdout. Prints nothing and exits 0 whenever
there's nothing useful to say — no brain, no files, unreadable files — because
a session start that fails noisily is worse than one that quietly loads nothing.
"""

import os
import sys
import json
import glob

BUDGET = 6000  # characters; ~1.5k tokens. Guards against a preference file
               # growing unbounded and quietly taxing every session.


def main():
    brain = os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
    if not os.path.isdir(brain):
        return 0

    paths = [os.path.join(brain, "graph", "profile.md")]
    paths += sorted(glob.glob(os.path.join(brain, "wiki", "preferences", "*.md")))

    chunks, used, skipped = [], 0, 0
    for p in paths:
        try:
            text = open(p, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            continue
        if not text:
            continue
        if used + len(text) > BUDGET:
            skipped += 1
            continue
        chunks.append(f"<!-- {os.path.relpath(p, brain)} -->\n{text}")
        used += len(text)

    if not chunks:
        return 0

    header = (
        "Loaded automatically from the user's brain at "
        f"{brain} — his profile and standing preferences. Treat these as how he "
        "wants to be worked with, not as background reading. The `keel` "
        "skill can pull projects, decisions, people and open loops on top of this; "
        "don't re-read these files, they're already here."
    )
    if skipped:
        header += (
            f" ({skipped} preference file(s) skipped — over the size budget; "
            "run /health to see what's grown.)"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": header + "\n\n" + "\n\n".join(chunks),
        },
        "suppressOutput": True,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never block a session start
