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
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
SRC = HERE / "condense.js"
PAGES = [HERE.parent / "sim" / "tasklot-sim.html"]
BEGIN = "/* ===== BEGIN condense.js ===== */"
END = "/* ===== END condense.js ===== */"

EXIT_CURRENT = 0
EXIT_STALE = 1
EXIT_NO_MARKERS = 2


def sync_one(path: Path, src: str, check: bool) -> int:
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
    name = path.name
    if not path.exists():
        print(f"{name}: not found - skipped")
        return EXIT_CURRENT

    page = path.read_text(encoding="utf-8")
    a = page.find(BEGIN)
    b = page.find(END)
    if a < 0 or b < 0:
        print(f"{name}: markers missing - add {BEGIN} / {END} around the inlined copy")
        return EXIT_NO_MARKERS

    if page[a + len(BEGIN):b].strip("\n") == src:
        print(f"{name}: condense.js copy is current")
        return EXIT_CURRENT
    if check:
        print(f"STALE: {name} carries an old copy of condense.js. Run: python3 tools/voice/sync_page.py")
        return EXIT_STALE

    path.write_text(page[:a + len(BEGIN)] + "\n" + src + "\n" + page[b:], encoding="utf-8")
    print(f"{name}: re-inlined condense.js")
    return EXIT_CURRENT


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Sync every page; returns the worst status as the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    src = SRC.read_text(encoding="utf-8").rstrip("\n")
    return max(sync_one(page, src, check) for page in PAGES)


if __name__ == "__main__":
    sys.exit(main())
