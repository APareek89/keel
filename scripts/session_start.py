#!/usr/bin/env python3
"""
SessionStart hook for the keel skill.

Loads the profile (graph/profile.md) and the global preferences (those in
wiki/preferences/ with no `about:`) into every session, so output is aligned
to how the user works without them having to re-brief anyone. A preference
scoped to a kind of work loads only when that work is in play — retrieval
brings it in, not this hook.

Emits the hook JSON envelope on stdout. Prints nothing and exits 0 whenever
there's nothing useful to say — no brain, no files, unreadable files — because
a session start that fails noisily is worse than one that quietly loads nothing.
"""

import os
import sys
import json

BUDGET = 6000  # characters; ~1.5k tokens. Guards against a preference file
               # growing unbounded and quietly taxing every session.


def main():
    brain_dir = os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
    if not os.path.isdir(brain_dir):
        return 0

    # brain.py decides what loads, so the hook, the Codex export and the MCP
    # server can never disagree about it
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import brain

    loaded, skipped = brain.standing_context(BUDGET)
    if not loaded:
        return 0

    header = (
        "Loaded automatically from the user's brain at "
        f"{brain_dir} — their profile and global preferences. Treat these as how "
        "they want to be worked with, not as background reading. Preferences "
        "scoped to a kind of work load when that work comes up. The `keel` skill "
        "can pull tasks, decisions, people and open loops on top of this; don't "
        "re-read these files, they're already here."
    )
    if skipped:
        header += (
            f" ({len(skipped)} file(s) skipped for size: {', '.join(skipped)}. "
            "Trim them, or scope preferences to the work they're about.)"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": header + "\n\n" + "\n\n".join(
                f"<!-- {rel} -->\n{text}" for rel, text in loaded),
        },
        "suppressOutput": True,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never block a session start
