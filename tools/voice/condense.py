#!/usr/bin/env python3
"""condense.py: command-line front door to the Condenser.

    python3 tools/voice/condense.py "I need to email the professor by Friday"
    echo "call mom" | python3 tools/voice/condense.py

Prints {"full", "lcd", "due", "raw"} as JSON. The rules live in
tasklot/condenser.py (Python) and condense.js (browser); this file keeps the
original command and the old function names working for anything that
imported them.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tasklot.condenser import (  # noqa: E402  (path set up above)
    LCD_TEXT, LCD_WIDTH, Condenser, ascii_only, clip, devowel, trim_phrases,
)

__all__ = ["LCD_TEXT", "LCD_WIDTH", "ascii_only", "clip", "condense", "devowel",
           "first_step", "lot_lines", "playback", "trim_phrases"]


def condense(transcript, width=LCD_TEXT):
    """Condense one memo; returns {"full", "lcd", "due", "raw"} as a dict."""
    return Condenser(width).condense(transcript).to_dict()


def first_step(text):
    """The read-back nudge for one task."""
    return Condenser.first_step(text)


def playback(task):
    """The whole spoken read-back for a task dict."""
    return Condenser().playback(task)


def lot_lines(lot, width=LCD_WIDTH):
    """The four padded LCD rows for a lot."""
    return Condenser.lot_lines(lot, width)


def main(argv=None):
    """Condense the arguments (or stdin) and print the result as JSON.

    Returns:
        int: process exit status, always 0.
    """
    argv = sys.argv[1:] if argv is None else argv
    text = " ".join(argv) or sys.stdin.read()
    print(json.dumps(condense(text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
