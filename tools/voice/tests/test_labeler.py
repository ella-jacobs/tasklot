"""Tests for the Labeler (optional LLM label upgrade) and its guards.

The model is never called: every test passes a fake runner. Covers DESIGN.md
E-21 (hallucinated labels rejected, using the real failures recorded in the
code), E-22 (timeout, error, empty or multi-line output), E-23 (too little said).
"""
import subprocess
import unittest
from unittest import mock

from tasklot.labeler import (
    MIN_CONTENT_WORDS, PROMPT, Labeler, claude_cli_runner, content_word_count, fit, invented,
    unrelated,
)
from tasklot.logs import LogCapture, silent


def fixed_runner(output):
    """A runner that ignores the prompt and returns `output`; records calls."""
    def run(prompt, timeout):
        run.calls.append((prompt, timeout))
        return output
    run.calls = []
    return run


def raising_runner(exc):
    """A runner that raises `exc`."""
    def run(prompt, timeout):
        raise exc
    return run


class InventedGuardTest(unittest.TestCase):
    """E-21: time/date words or digits the transcript never contained."""

    def test_real_failures_are_caught(self):
        self.assertEqual(invented("PAPER DUE TONIGHT", "write the paper for english class"), "tonight")
        self.assertEqual(invented("ESSAY FRI", "finish the history essay draft"), "fri")
        self.assertEqual(invented("CALL AT 5", "call the dentist office back"), "5")

    def test_words_that_were_said_pass(self):
        self.assertIsNone(invented("ESSAY FRI", "finish the essay by friday"))
        self.assertIsNone(invented("ENGS21 HW MIDNITE", "homework due at midnight for engs 21"))
        self.assertIsNone(invented("CALL DENTIST", "I need to call the dentist"))


class UnrelatedGuardTest(unittest.TestCase):
    """E-21: a label that shares no word with what was said."""

    def test_place_order_is_rejected(self):
        self.assertTrue(unrelated("PLACE ORDER", "How do you tell where that's going?"))

    def test_abbreviations_count_as_related(self):
        self.assertFalse(unrelated("EMAIL PROF", "email my professor about the project"))
        self.assertFalse(unrelated("PROJ REPORT", "write up the project"))

    def test_abbreviation_without_shared_prefix_is_unrelated(self):
        # Known limit: "HW" shares no 3-letter prefix with "homework", so a
        # label made only of such abbreviations is rejected (the safe side).
        self.assertTrue(unrelated("HW", "finish the homework"))

    def test_nothing_to_judge_passes(self):
        self.assertFalse(unrelated("A", "the"))


class FitTest(unittest.TestCase):
    """Over-long labels are trimmed word by word, or hard-cut if one word."""

    def test_word_trim(self):
        self.assertEqual(fit("EMAIL PROFESSOR ABOUT POSTER", 18), "EMAIL PROFESSOR")

    def test_single_long_word(self):
        self.assertEqual(fit("A" * 25, 18), "A" * 18)


class LabelerTest(unittest.TestCase):
    """label() end to end with fake runners."""

    TRANSCRIPT = "homework due at midnight for engines 21"

    def test_good_label_is_returned(self):
        runner = fixed_runner("ENGS21 HW MIDNITE")
        labeler = Labeler(runner=runner, timeout=7, log=silent)
        self.assertEqual(labeler.label(self.TRANSCRIPT), "ENGS21 HW MIDNITE")
        prompt, timeout = runner.calls[0]
        self.assertEqual(prompt, PROMPT % self.TRANSCRIPT)
        self.assertEqual(timeout, 7)

    def test_disabled_never_calls_runner(self):
        runner = fixed_runner("X")
        self.assertIsNone(Labeler(runner=runner, enabled=False, log=silent).label(self.TRANSCRIPT))
        self.assertEqual(runner.calls, [])

    def test_too_little_said_skips_model(self):
        # E-23
        runner = fixed_runner("PAPER DUE TONIGHT")
        log = LogCapture()
        self.assertLess(content_word_count("Paper."), MIN_CONTENT_WORDS)
        self.assertIsNone(Labeler(runner=runner, log=log).label("Paper."))
        self.assertEqual(runner.calls, [])
        self.assertIn("too little was said", log.text())

    def test_timeout_and_errors_fall_back(self):
        # E-22
        for exc in (subprocess.TimeoutExpired("claude", 25), FileNotFoundError("claude"),
                    RuntimeError("boom")):
            with self.subTest(exc=type(exc).__name__):
                labeler = Labeler(runner=raising_runner(exc), log=silent)
                self.assertIsNone(labeler.label(self.TRANSCRIPT))

    def test_empty_output_is_none(self):
        for output in ("", "   \n  ", None, '""'):
            with self.subTest(output=output):
                self.assertIsNone(Labeler(runner=fixed_runner(output), log=silent)
                                  .label(self.TRANSCRIPT))

    def test_multiline_quoted_output_is_collapsed(self):
        labeler = Labeler(runner=fixed_runner('"ENGS21\nHW MIDNITE."\n'), log=silent)
        self.assertEqual(labeler.label(self.TRANSCRIPT), "ENGS21 HW MIDNITE")

    def test_long_output_is_trimmed_to_width(self):
        labeler = Labeler(runner=fixed_runner("ENGS21 HOMEWORK DUE MIDNIGHT"), log=silent)
        out = labeler.label(self.TRANSCRIPT)
        self.assertEqual(out, "ENGS21 HOMEWORK")
        self.assertLessEqual(len(out), 18)

    def test_non_ascii_output_is_flattened(self):
        labeler = Labeler(runner=fixed_runner("HW \u2014 ENGS21 \U0001F600"), log=silent)
        self.assertEqual(labeler.label(self.TRANSCRIPT), "HW - ENGS21")

    def test_guards_reject(self):
        log = LogCapture()
        said = "write the paper for english class"
        self.assertIsNone(Labeler(runner=fixed_runner("PAPER DUE TONIGHT"), log=log).label(said))
        self.assertIn("invented 'tonight'", log.text())
        self.assertIsNone(Labeler(runner=fixed_runner("PLACE ORDER"), log=log).label(said))
        self.assertIn("shares no word", log.text())


class ClaudeCliRunnerTest(unittest.TestCase):
    """The default runner's command line and exit-status handling, with
    subprocess.run replaced so no CLI or model is ever called."""

    def fake_run(self, returncode=0, stdout="", stderr=""):
        def run(cmd, **kwargs):
            run.calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
        run.calls = []
        return run

    def test_no_tools_and_no_saved_session(self):
        run = self.fake_run(stdout="EMAIL PROF\n")
        with mock.patch("tasklot.labeler.subprocess.run", run):
            self.assertEqual(claude_cli_runner("the prompt", 9), "EMAIL PROF\n")
        cmd, kwargs = run.calls[0]
        self.assertEqual(cmd, ["claude", "-p", "--tools", "", "--no-session-persistence",
                               "the prompt"])
        self.assertEqual(kwargs["timeout"], 9)

    def test_non_zero_exit_raises_and_labeler_falls_back(self):
        # An error printed to stdout (a login prompt, a quota message) must
        # never become a candidate label.
        run = self.fake_run(returncode=1, stdout="Invalid API key - please run /login",
                            stderr="not logged in")
        with mock.patch("tasklot.labeler.subprocess.run", run):
            with self.assertRaises(RuntimeError) as ctx:
                claude_cli_runner("the prompt", 9)
            self.assertIn("not logged in", str(ctx.exception))
            log = LogCapture()
            self.assertIsNone(Labeler(log=log).label("invite the team to the planning meeting"))
            self.assertIn("falling back to rules", log.text())


if __name__ == "__main__":
    unittest.main()
