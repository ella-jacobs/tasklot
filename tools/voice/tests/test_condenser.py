"""Tests for the Condenser (memo -> 18-character LCD label).

Pins the behaviour from before the OOP refactor: every case in cases.json
produces exactly the same full/lcd/due output. Adds the DESIGN.md edge cases for
text width and character set (E-15, E-17, E-18, E-19) and checks the simulator's
inlined copy of condense.js is current. Agreement with condense.js on the same
inputs is checked in test_cross_language.py.
"""
import json
import os
import random
import subprocess
import sys
import unittest

import condense as legacy
from tasklot.condenser import (
    DEFAULT_NUDGE, LCD_TEXT, LCD_WIDTH, Condensed, Condenser, ascii_only, clip,
    devowel, trim_phrases,
)

VOICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(VOICE_DIR, "cases.json")

# Vocabulary for the property test: real task words, filler, intent prefixes,
# due hints, abbreviation targets, and long words that force truncation.
WORDS = ("um uh okay so I need to remind me email call the professor about whether "
         "we still need poster by Friday tonight at 4pm meeting homework project "
         "library and with for before after print reader coupon battery pack "
         "charge reconcile deck against toolbox disclosure presentation "
         "extraordinarily-long-hyphenated-word. Then! really just basically").split()
PROPERTY_SEED = 2024      # fixed so a failure is reproducible
PROPERTY_SAMPLES = 400


def load_cases():
    """Read the shared fixtures: {"width": int, "cases": [{"in", "full", "lcd", "due"}]}."""
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def random_memos(seed=PROPERTY_SEED, count=PROPERTY_SAMPLES):
    """Deterministic pseudo-random memos built from WORDS.

    Returns:
        list[str]: `count` memos of 1 to 30 words.
    """
    rng = random.Random(seed)
    return [" ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 30)))
            for _ in range(count)]


class CasesJsonTest(unittest.TestCase):
    """Every fixture in cases.json, field by field (E-18 and E-19 are in there)."""

    def test_every_case_matches(self):
        spec = load_cases()
        condenser = Condenser(spec["width"])
        for case in spec["cases"]:
            with self.subTest(text=case["in"][:50]):
                got = condenser.condense(case["in"])
                self.assertIsInstance(got, Condensed)
                for key in ("full", "lcd", "due"):
                    self.assertEqual(getattr(got, key), case[key], key)

    def test_legacy_function_matches_class(self):
        # condense.py keeps the old function API for the offline CLI and scripts.
        for case in load_cases()["cases"]:
            self.assertEqual(legacy.condense(case["in"]),
                             Condenser().condense(case["in"]).to_dict())


class WidthTest(unittest.TestCase):
    """E-15: no input ever produces a label wider than the LCD text area."""

    def test_label_never_exceeds_width(self):
        condenser = Condenser()
        for memo in random_memos():
            with self.subTest(memo=memo):
                self.assertLessEqual(len(condenser.condense(memo).lcd), LCD_TEXT)

    def test_other_widths_are_respected(self):
        for width in (8, 12, 18, 30):
            condenser = Condenser(width)
            for memo in random_memos(count=50):
                self.assertLessEqual(len(condenser.condense(memo).lcd), width)

    def test_exactly_18_passes_untouched_19_is_devowelled(self):
        # E-19
        c = Condenser()
        self.assertEqual(c.condense("Charge battery now").lcd, "Charge battery now")
        self.assertEqual(c.condense("Print reader coupon").lcd, "Print reader coupn")


class EmptyInputTest(unittest.TestCase):
    """E-18: empty, whitespace, punctuation-only, and None all give empty fields."""

    def test_empty_like_inputs(self):
        for text in ("", "   ", "   ...   ", None, "\t\n"):
            with self.subTest(text=text):
                got = Condenser().condense(text)
                self.assertEqual((got.full, got.lcd, got.due), ("", "", ""))

    def test_raw_keeps_the_flattened_input(self):
        # Punctuation-only input keeps its raw text; only full/lcd/due are empty.
        self.assertEqual(Condenser().condense("   ...   ").raw, "...")
        self.assertEqual(Condenser().condense(None), Condensed("", "", "", ""))


class NonAsciiTest(unittest.TestCase):
    """E-17: the LCD ROM is ASCII; smart punctuation maps, everything else drops."""

    def test_smart_punctuation_is_flattened(self):
        self.assertEqual(ascii_only("don\u2019t \u201cforget\u201d \u2013 now\u2026"),
                         "don't \"forget\" - now...")

    def test_accents_and_emoji_are_dropped(self):
        # Current behaviour, kept deliberately: accents are dropped, not
        # transliterated (DESIGN.md E-17 leaves that decision open).
        self.assertEqual(ascii_only("caf\u00e9 \U0001F600 run"), "caf run")

    def test_fully_non_ascii_transcript_is_empty(self):
        self.assertEqual(Condenser().condense("\u4f60\u597d\u4e16\u754c").lcd, "")

    def test_label_is_always_printable_ascii(self):
        got = Condenser().condense("Email the \u00e9cole about the \u2018poster\u2019")
        self.assertTrue(all(" " <= ch <= "~" for ch in got.lcd + got.full))


class HelperTest(unittest.TestCase):
    """The squeeze stages on their own."""

    def test_clip_prefers_word_boundary_only_when_it_keeps_most(self):
        self.assertEqual(clip("Book a study room in the library", 18), "Book a study room")
        # Boundary at index 1 would keep 1 of 10 characters, so cut hard instead.
        self.assertEqual(clip("A verylongwordhere", 10), "A verylong")

    def test_trim_phrases_keeps_two_word_verb_phrase(self):
        self.assertEqual(trim_phrases("Print the reader coupon before class", 18),
                         "Print the reader coupon")
        self.assertEqual(trim_phrases("Go to the store", 5), "Go to the store")

    def test_devowel_only_when_close(self):
        self.assertEqual(devowel("Print reader coupon", 18), "Print reader coupn")
        self.assertEqual(devowel("this is far far too long to squeeze", 18),
                         "this is far far too long to squeeze")


class LotLinesTest(unittest.TestCase):
    """The four LCD rows: always four, always 20 wide, space order = priority."""

    def test_four_lines_of_full_width(self):
        lines = Condenser.lot_lines([{"lcd": "Email the Prof"}, "Call mom", None, None])
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(len(line), LCD_WIDTH)
        self.assertEqual(lines[2].strip(), "3>-")

    def test_short_or_missing_lot(self):
        self.assertEqual([l.strip() for l in Condenser.lot_lines(None)],
                         ["1>-", "2>-", "3>-", "4>-"])
        self.assertEqual(Condenser.lot_lines(["x"])[1].strip(), "2>-")

    def test_long_label_is_clipped_to_row(self):
        lines = Condenser.lot_lines(["a" * 40])
        self.assertEqual(lines[0], "1>" + "a" * 18)


class PlaybackTest(unittest.TestCase):
    """The spoken read-back and its nudge."""

    def test_playback_with_due(self):
        task = Condenser().condense("remind me to charge the battery pack tonight")
        self.assertEqual(Condenser().playback(task),
                         "Charge the battery pack. Due tonight. "
                         "Go plug it in. That is the whole task.")

    def test_playback_of_nothing_is_empty(self):
        self.assertEqual(Condenser().playback(None), "")
        self.assertEqual(Condenser().playback({"full": ""}), "")

    def test_first_step_falls_back(self):
        self.assertEqual(Condenser.first_step("ponder the universe"), DEFAULT_NUDGE)
        self.assertEqual(Condenser.first_step("email the professor"),
                         "Just open Gmail and get started.")


class SimulatorCopyTest(unittest.TestCase):
    """The simulator page carries an inlined copy of condense.js; a stale copy
    would show different words on the page than the laptop sends to the LCD."""

    def test_page_copy_is_current(self):
        result = subprocess.run(
            [sys.executable, os.path.join(VOICE_DIR, "sync_page.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


class CommandLineTest(unittest.TestCase):
    """`python3 condense.py <text>` still prints the same JSON."""

    def test_cli_output(self):
        result = subprocess.run([sys.executable, os.path.join(VOICE_DIR, "condense.py"),
                                 "call", "mom"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout),
                         {"full": "Call mom", "lcd": "Call mom", "due": "", "raw": "call mom"})


if __name__ == "__main__":
    unittest.main()
