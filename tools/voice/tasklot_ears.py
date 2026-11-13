#!/usr/bin/env python3
"""tasklot_ears.py: start the live TaskLot daemon.

    python3 tools/voice/tasklot_ears.py [--port PORT] [--no-llm]

Holds the serial port to the board. When a blank car passes the speaker reader
it records from the mic; when the car is parked it transcribes locally with
whisper.cpp, shortens the task to 18 characters, and sends `CAR n <label>` so
the text lands on the LCD. Nothing else may hold the port while it runs (no
Arduino Serial Monitor, no simulator page).

This script is the original command, kept working; the code lives in the
tasklot package (tasklot/ears.py) and is the same as `python3 -m tasklot ears`.
Configuration is by environment variable; see tasklot/config.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tasklot.cli import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main(["ears"] + sys.argv[1:]))
