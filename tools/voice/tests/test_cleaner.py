"""Tests for TranscriptCleaner (whisper noise -> clean sentences).

Expected outputs were captured from clean_transcript() in the daemon as
imported, so the refactor keeps behaviour identical. Covers DESIGN.md E-02
(filler-only transcripts become empty).
"""
import unittest

from tasklot.cleaner import TranscriptCleaner

# (raw whisper output, cleaned) pairs pinned from the pre-refactor code.
PINNED = [
    ("Hello?", ""),
    ("Um. Okay.", ""),
    ("[BLANK_AUDIO]", ""),
    (" [BLANK_AUDIO] (music) ", ""),
    ("Hello, I need to email the professor.", "I need to email the professor."),
    ("Hello. >> I need to call mom. >> I need to call mom.", "I need to call mom."),
    ("Okay so um I have to finish the lab report. Thank you.",
     "I have to finish the lab report."),
    ("Hi there, please buy milk", "buy milk."),
    ("email Bob >> email Bob about lunch", "email Bob. email Bob about lunch."),
    ("Yeah. Bye.", "Bye."),
    ("...", "..."),
]


class CleanTest(unittest.TestCase):
    """clean() output for every pinned input."""

    def test_pinned_outputs(self):
        cleaner = TranscriptCleaner()
        for raw, want in PINNED:
            with self.subTest(raw=raw):
                self.assertEqual(cleaner.clean(raw), want)


class FillerOnlyTest(unittest.TestCase):
    """E-02: a transcript of only filler is treated as empty by the daemon."""

    def test_filler_only_is_empty(self):
        cleaner = TranscriptCleaner()
        for raw in ("Hello?", "Um. Okay.", "[BLANK_AUDIO]", "...", "  "):
            with self.subTest(raw=raw):
                self.assertTrue(cleaner.is_empty(cleaner.clean(raw)))

    def test_real_task_is_not_empty(self):
        cleaner = TranscriptCleaner()
        self.assertFalse(cleaner.is_empty(cleaner.clean("Um, call mom")))


class StripLeadTest(unittest.TestCase):
    """Leading greetings come off repeatedly; mid-sentence words stay."""

    def test_stacked_greetings(self):
        self.assertEqual(TranscriptCleaner.strip_lead("Hey there, okay, um, so call mom"),
                         "call mom")

    def test_words_inside_are_kept(self):
        self.assertEqual(TranscriptCleaner.strip_lead("call mom, okay"), "call mom, okay")


if __name__ == "__main__":
    unittest.main()
