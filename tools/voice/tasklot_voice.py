#!/usr/bin/env python3
"""tasklot_voice.py: voice memo or typed text -> a task, on the laptop.

The offline path, for when there is no live order: a memo recorded on a phone,
or typed text to load the demo quickly. Output lands in tasks.json next to this
script (override with TASKLOT_TASKS_FILE).

    # a recording -> a task on car 2 (needs TASKLOT_WHISPER_SCRIPT)
    python3 tasklot_voice.py memo.m4a --car 2

    # skip the audio, just condense text
    python3 tasklot_voice.py --text "I need to email the professor by Friday" --car 1

    # the newest Apple Voice Memo
    python3 tasklot_voice.py --latest-memo --car 3

    # watch a folder: drop a recording in inbox/ and it becomes the next task
    python3 tasklot_voice.py --watch inbox/

    # push tasks.json to the board (close the simulator and the daemon first)
    python3 tasklot_voice.py --push --port /dev/cu.usbmodem101

This script is the original command, kept working; the code lives in the
tasklot package (tasklot/offline.py) and is the same as `python3 -m tasklot voice`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tasklot.cli import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main(["voice"] + sys.argv[1:]))
