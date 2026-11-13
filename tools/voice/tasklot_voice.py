#!/usr/bin/env python3
"""TaskLot — voice memo -> task, on the laptop.

    recording  ->  whisper  ->  condense  ->  { tasks.json , the LCD }
                 (mechanical)  (judgment)

This is the OFFLINE path. The live demo normally dictates straight in
the browser page (Chrome's speech recognition, no install, instant). Use this
one when there's no internet in the room, when a memo was recorded on a phone,
or when you want a real transcript of a long ramble instead of live dictation.

Transcription is delegated to an external faster-whisper script named by the
TASKLOT_WHISPER_SCRIPT environment variable (it takes an audio path and prints
the transcript). Nothing leaves the machine.

USAGE
  # a recording -> a task on car 2
  python3 tasklot_voice.py memo.m4a --car 2

  # skip the audio, just condense text (fastest way to load the demo)
  python3 tasklot_voice.py --text "I need to email the professor by Friday" --car 1

  # the newest Apple Voice Memo, whatever it was
  python3 tasklot_voice.py --latest-memo --car 3

  # watch a folder: drop any recording in inbox/ and it becomes the next task
  python3 tasklot_voice.py --watch inbox/

  # push what's in tasks.json straight to the Mega (close the live page first -
  # only one program can hold the serial port)
  python3 tasklot_voice.py --push --port /dev/cu.usbmodem14101

Output lands in tasks.json next to this script. Load that file in
the browser page with "Load tasks file" and the page pushes it to the LCD over
its own connection - which avoids fighting over the port.

AI disclosure: written with Claude (Anthropic) to Ella's spec. Credit it.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import condense as C

HERE = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(HERE, "tasks.json")
WHISPER = os.environ.get("TASKLOT_WHISPER_SCRIPT", "")
VOICE_MEMO_DIR = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings")
AUDIO_EXT = (".m4a", ".wav", ".mp3", ".aiff", ".aif", ".caf", ".qta", ".mp4")
MAX_CARS = 8


# --------------------------------------------------------------------------
# mechanical half
# --------------------------------------------------------------------------
def transcribe(path):
    """Audio -> text, via the faster-whisper script named by TASKLOT_WHISPER_SCRIPT."""
    if not WHISPER or not os.path.exists(WHISPER):
        sys.exit("TASKLOT_WHISPER_SCRIPT is unset or missing (%r)\n"
                 "Set it to a transcriber script, or use --text to skip transcription." % WHISPER)
    print("  transcribing %s ..." % os.path.basename(path), file=sys.stderr)
    r = subprocess.run([sys.executable, WHISPER, path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("whisper failed: %s" % (r.stderr.strip() or r.returncode))
    return r.stdout.strip()


def latest_memo():
    """Newest Apple Voice Memo on disk. Needs Full Disk Access for the terminal —
    if it comes back empty that's why."""
    if not os.path.isdir(VOICE_MEMO_DIR):
        sys.exit("Voice Memos folder not readable. Grant Full Disk Access, or pass a file.")
    files = [os.path.join(VOICE_MEMO_DIR, f) for f in os.listdir(VOICE_MEMO_DIR)
             if f.lower().endswith(AUDIO_EXT)]
    if not files:
        sys.exit("No recordings found in %s" % VOICE_MEMO_DIR)
    return max(files, key=os.path.getmtime)


# --------------------------------------------------------------------------
# task store
# --------------------------------------------------------------------------
def load_tasks():
    if os.path.exists(TASKS):
        try:
            return json.load(open(TASKS))
        except (ValueError, OSError):
            print("  tasks.json unreadable, starting fresh", file=sys.stderr)
    return {"updated": "", "cars": {}}


def save_tasks(db):
    db["updated"] = datetime.now().isoformat(timespec="seconds")
    with open(TASKS, "w") as f:
        json.dump(db, f, indent=2)
    return TASKS


def next_free_car(db):
    for n in range(1, MAX_CARS + 1):
        if str(n) not in db["cars"]:
            return n
    return None


def add_task(db, text, car=None, source=""):
    task = C.condense(text)
    if not task["full"]:
        print("  nothing usable in that recording - skipped", file=sys.stderr)
        return None, None
    if car is None:
        car = next_free_car(db)
        if car is None:
            sys.exit("All %d cars have tasks. Pass --car N to overwrite one." % MAX_CARS)
    task["source"] = source
    task["recorded"] = datetime.now().isoformat(timespec="seconds")
    db["cars"][str(car)] = task
    return car, task


# --------------------------------------------------------------------------
# the LCD, on paper
# --------------------------------------------------------------------------
def preview(db, order=None):
    """What the screen would say. Space order is priority order, so `order` is
    the car parked in space 1..4 — without hardware, just cars 1..4."""
    order = order or [1, 2, 3, 4]
    lot = [db["cars"].get(str(n)) for n in order]
    print("\n   +--------------------+")
    for line in C.lot_lines(lot):
        print("   |%s|" % line)
    print("   +--------------------+\n")


# --------------------------------------------------------------------------
# serial push (only when the live page is NOT connected)
# --------------------------------------------------------------------------
def push(db, port, baud=9600):
    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial not installed:  python3 -m pip install --user pyserial")
    print("  opening %s at %d ..." % (port, baud), file=sys.stderr)
    with serial.Serial(port, baud, timeout=2) as s:
        # Opening the port toggles DTR and RESETS the Mega. Its RAM car list is
        # wiped, so wait for the boot banner before sending anything.
        time.sleep(2.0)
        s.reset_input_buffer()
        for n in sorted(db["cars"], key=int):
            line = "CAR %s %s\n" % (n, db["cars"][n]["lcd"])
            s.write(line.encode("ascii", "ignore"))
            s.flush()
            time.sleep(0.08)
            print("  -> " + line.strip(), file=sys.stderr)
        s.write(b"LOT\n")
        s.flush()
        time.sleep(0.4)
        out = s.read(s.in_waiting or 1).decode("ascii", "ignore")
        if out.strip():
            print("\n" + out.strip())


# --------------------------------------------------------------------------
def handle(db, text, car, source, args):
    n, task = add_task(db, text, car, source)
    if n is None:
        return
    print("\n  CAR %d" % n)
    print("  full : %s" % task["full"])
    print("  lcd  : %-18s  (%d/18)" % (task["lcd"], len(task["lcd"])))
    if task["due"]:
        print("  due  : %s" % task["due"])
    save_tasks(db)


def main():
    p = argparse.ArgumentParser(description="TaskLot voice memo -> task")
    p.add_argument("audio", nargs="*", help="audio file(s) to transcribe")
    p.add_argument("--text", help="skip transcription, condense this text")
    p.add_argument("--latest-memo", action="store_true", help="use the newest Apple Voice Memo")
    p.add_argument("--watch", metavar="DIR", help="watch DIR for new recordings")
    p.add_argument("--car", type=int, help="assign to car N (default: next free)")
    p.add_argument("--push", action="store_true", help="send tasks.json to the Mega")
    p.add_argument("--port", help="serial port, e.g. /dev/cu.usbmodem14101")
    p.add_argument("--clear", action="store_true", help="empty tasks.json")
    args = p.parse_args()

    db = load_tasks()

    if args.clear:
        db = {"updated": "", "cars": {}}
        print("  cleared %s" % save_tasks(db))
        return

    if args.text:
        handle(db, args.text, args.car, "typed", args)
    for f in args.audio:
        handle(db, transcribe(f), args.car, os.path.basename(f), args)
        args.car = None          # only the first one honours --car
    if args.latest_memo:
        f = latest_memo()
        handle(db, transcribe(f), args.car, os.path.basename(f), args)

    if args.watch:
        watch(db, args.watch, args)
        return

    if db["cars"]:
        preview(db)
        print("  saved %s" % TASKS)
    if args.push:
        if not args.port:
            sys.exit("--push needs --port. List them:  ls /dev/cu.usbmodem*")
        push(db, args.port)
    elif not db["cars"]:
        p.print_help()


def watch(db, folder, args):
    """Drop a recording in the folder and it becomes the next task. The hands-off
    demo path: record on a phone, AirDrop into inbox/, watch the screen fill."""
    os.makedirs(folder, exist_ok=True)
    seen = {f for f in os.listdir(folder) if f.lower().endswith(AUDIO_EXT)}
    print("  watching %s - drop a recording in. ctrl-c to stop." % folder)
    print("  (%d file(s) already there, ignoring those)" % len(seen))
    try:
        while True:
            time.sleep(1.5)
            now = {f for f in os.listdir(folder) if f.lower().endswith(AUDIO_EXT)}
            for f in sorted(now - seen):
                path = os.path.join(folder, f)
                # wait for the copy to finish before whisper opens it
                size = -1
                while size != os.path.getsize(path):
                    size = os.path.getsize(path)
                    time.sleep(0.6)
                handle(db, transcribe(path), None, f, args)
                preview(db)
                if args.push and args.port:
                    push(db, args.port)
            seen = now
    except KeyboardInterrupt:
        print("\n  stopped. %s" % TASKS)


if __name__ == "__main__":
    main()
