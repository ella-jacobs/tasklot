#!/usr/bin/env python3
"""Runs cases.json against condense.py. Twin of test_condense.js.
If one passes and the other fails, the port drifted — fix it before the demo,
because the page and the LCD would be showing different words for the same memo."""
import json
import os
import sys

import condense as C

HERE = os.path.dirname(os.path.abspath(__file__))
spec = json.load(open(os.path.join(HERE, "cases.json")))
fail = 0

for c in spec["cases"]:
    got = C.condense(c["in"], width=spec["width"])
    for k in ("full", "lcd", "due"):
        if got[k] != c[k]:
            fail += 1
            print("FAIL  %.50s\n      %s: want %r\n           got  %r" % (json.dumps(c["in"]), k, c[k], got[k]))
    if len(got["lcd"]) > spec["width"]:
        fail += 1
        print("FAIL  lcd too wide (%d): %s" % (len(got["lcd"]), got["lcd"]))

lines = C.lot_lines([{"lcd": "Email the Prof"}, "Call mom", None, None])
if len(lines) != 4:
    fail += 1
    print("FAIL  lot_lines did not return 4 lines")
for i, l in enumerate(lines):
    if len(l) != C.LCD_WIDTH:
        fail += 1
        print("FAIL  line %d is %d chars, want %d" % (i + 1, len(l), C.LCD_WIDTH))
if lines[2].strip() != "3>-":
    fail += 1
    print("FAIL  empty space should render '3>-', got %r" % lines[2])

# The live page carries an inlined COPY of condense.js. If it has drifted, the
# page and the CLI show different words for the same memo — fail here, not in front of an audience.
import subprocess
r = subprocess.run([sys.executable, os.path.join(HERE, "sync_page.py"), "--check"],
                   capture_output=True, text=True)
if r.returncode:
    fail += 1
    print("FAIL  " + r.stdout.strip())

print("\n%d failure(s)" % fail if fail else "py: %d cases ok, page copy current" % len(spec["cases"]))
sys.exit(1 if fail else 0)
