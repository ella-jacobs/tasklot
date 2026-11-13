"""Tests for the rule-based condenser (memo -> 18-character LCD label).

Pins the current behaviour before the OOP refactor: every case in cases.json must
produce exactly the same full/lcd/due output, the four lot lines are always 20
characters, and the simulator's inlined copy of condense.js is current.
"""
import json
import os
import subprocess
import sys
import unittest

import condense as C

VOICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(VOICE_DIR, "cases.json")


def load_cases():
    """Read the shared fixtures.

    Returns:
        dict: {"width": int, "cases": [{"in", "full", "lcd", "due"}, ...]}
    """
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


class CasesJsonTest(unittest.TestCase):
    """Every fixture in cases.json, field by field."""

    def test_every_case_matches(self):
        spec = load_cases()
        for case in spec["cases"]:
            with self.subTest(text=case["in"][:50]):
                got = C.condense(case["in"], width=spec["width"])
                for key in ("full", "lcd", "due"):
                    self.assertEqual(got[key], case[key], key)
                self.assertLessEqual(len(got["lcd"]), spec["width"])


class LotLinesTest(unittest.TestCase):
    """The four LCD lines must always be exactly 20 characters, or the LCD keeps
    stale text from a previous, longer write hanging off the end."""

    def test_four_lines_of_full_width(self):
        lines = C.lot_lines([{"lcd": "Email the Prof"}, "Call mom", None, None])
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(len(line), C.LCD_WIDTH)
        self.assertEqual(lines[2].strip(), "3>-")


class SimulatorCopyTest(unittest.TestCase):
    """The simulator page carries an inlined copy of condense.js; a stale copy
    would show different words on the page than the laptop sends to the LCD."""

    def test_page_copy_is_current(self):
        result = subprocess.run(
            [sys.executable, os.path.join(VOICE_DIR, "sync_page.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
