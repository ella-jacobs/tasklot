#!/usr/bin/env python3
"""Re-inline condense.js into the simulator page (tools/sim/tasklot-sim.html).

The page carries a COPY of condense.js rather than a <script src> to it,
so it keeps working with no network and no file:// loading surprises in a lab
machine's Chrome. That copy has to be regenerated whenever the source changes:

    python3 tools/voice/sync_page.py          # write the copy
    python3 tools/voice/sync_page.py --check   # just say whether it's stale

test_condense.py runs --check, so a drifted page fails the tests instead of
silently showing different words on the screen than in the CLI.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "condense.js")
PAGES = [
    os.path.join(os.path.dirname(HERE), "sim", "tasklot-sim.html"),    # the bench simulator
]
BEGIN = "/* ===== BEGIN condense.js ===== */"
END = "/* ===== END condense.js ===== */"


def sync_one(path, src, check):
    name = os.path.basename(path)
    if not os.path.exists(path):
        print("%s: not found - skipped" % name)
        return 0

    page = open(path).read()
    a = page.find(BEGIN)
    b = page.find(END)
    if a < 0 or b < 0:
        print("%s: markers missing - add %s / %s around the inlined copy" % (name, BEGIN, END))
        return 2

    if page[a + len(BEGIN):b].strip("\n") == src:
        print("%s: condense.js copy is current" % name)
        return 0
    if check:
        print("STALE: %s carries an old copy of condense.js. Run: python3 %s" % (name, __file__))
        return 1

    open(path, "w").write(page[:a + len(BEGIN)] + "\n" + src + "\n" + page[b:])
    print("%s: re-inlined condense.js" % name)
    return 0


def main():
    check = "--check" in sys.argv
    src = open(SRC).read().rstrip("\n")
    return max(sync_one(p, src, check) for p in PAGES)


if __name__ == "__main__":
    sys.exit(main())
