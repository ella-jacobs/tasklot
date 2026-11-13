#!/usr/bin/env python3
"""Re-inline condense.js into the simulator page (tools/sim/tasklot-sim.html).

The page carries a copy of condense.js between BEGIN/END marker comments rather
than a <script src> to it, so it works with no network and no file:// loading
surprises in a lab machine's browser. That copy has to be regenerated whenever
condense.js changes:

    python3 tools/voice/sync_page.py           # write the copy
    python3 tools/voice/sync_page.py --check   # exit 1 if the copy is stale

tests/test_condenser.py runs --check, so a stale page fails the tests instead of
quietly showing different words in the simulator than on the LCD.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "condense.js")
PAGES = [
    os.path.join(os.path.dirname(HERE), "sim", "tasklot-sim.html"),
]
BEGIN = "/* ===== BEGIN condense.js ===== */"
END = "/* ===== END condense.js ===== */"

EXIT_CURRENT = 0
EXIT_STALE = 1
EXIT_NO_MARKERS = 2


def sync_one(path, src, check):
    """Refresh (or just check) the inlined copy in one page.

    Args:
        path: the HTML page.
        src: the current condense.js source, without a trailing newline.
        check: if True, report a stale copy instead of rewriting it.

    Returns:
        int: EXIT_CURRENT if current (or rewritten, or the page is missing),
        EXIT_STALE if stale in check mode, EXIT_NO_MARKERS if the markers are missing.

    Side effects:
        Rewrites the page when it is stale and check is False; prints one line.
    """
    name = os.path.basename(path)
    if not os.path.exists(path):
        print("%s: not found - skipped" % name)
        return EXIT_CURRENT

    with open(path, encoding="utf-8") as f:
        page = f.read()
    a = page.find(BEGIN)
    b = page.find(END)
    if a < 0 or b < 0:
        print("%s: markers missing - add %s / %s around the inlined copy" % (name, BEGIN, END))
        return EXIT_NO_MARKERS

    if page[a + len(BEGIN):b].strip("\n") == src:
        print("%s: condense.js copy is current" % name)
        return EXIT_CURRENT
    if check:
        print("STALE: %s carries an old copy of condense.js. Run: python3 tools/voice/sync_page.py" % name)
        return EXIT_STALE

    with open(path, "w", encoding="utf-8") as f:
        f.write(page[:a + len(BEGIN)] + "\n" + src + "\n" + page[b:])
    print("%s: re-inlined condense.js" % name)
    return EXIT_CURRENT


def main(argv=None):
    """Sync every page; returns the worst status as the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    with open(SRC, encoding="utf-8") as f:
        src = f.read().rstrip("\n")
    return max(sync_one(p, src, check) for p in PAGES)


if __name__ == "__main__":
    sys.exit(main())
