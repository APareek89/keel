#!/usr/bin/env python3
"""
SessionStart hook for the keel skill.

Kept as a thin shim: the implementation moved to `autobrain.py session-start`,
which loads the same profile and preferences and adds a live-topics block
measured from the user's own transcripts. Point hooks at either path.

Emits the hook JSON envelope on stdout. Prints nothing and exits 0 whenever
there's nothing useful to say — a session start that fails noisily is worse
than one that quietly loads nothing.
"""
import os
import sys
import runpy


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.argv = [os.path.join(here, "autobrain.py"), "session-start", "--days", "14"]
    runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # never block a session start
