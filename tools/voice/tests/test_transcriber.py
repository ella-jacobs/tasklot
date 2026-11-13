"""Tests for the transcribers, with every subprocess replaced by a fake.

Covers DESIGN.md E-01 (empty recording), E-06 (startup check) and E-07
(whisper timeout), plus the offline ScriptTranscriber and the FakeTranscriber.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tasklot.logs import LogCapture, silent
from tasklot.transcriber import (
    MIN_WAV_BYTES, FakeTranscriber, ScriptTranscriber, Transcriber, TranscriptionError,
)


class TranscriberTest(unittest.TestCase):
    """whisper-cli wrapper with subprocess.run mocked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self.tmp.name) / "order.wav"
        self.log = LogCapture()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def transcriber(self, stdout="", exc=None):
        def runner(cmd, **kwargs):
            self.calls.append((cmd, kwargs))
            if exc:
                raise exc
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        return Transcriber("whisper-cli", "/models/base.bin", timeout=90, runner=runner,
                           which=lambda name: None, log=self.log)

    def test_transcribes_and_collapses_lines(self):
        self.wav.write_bytes(b"\0" * MIN_WAV_BYTES)
        t = self.transcriber(stdout="\n Email the professor\n about the poster. \n")
        self.assertEqual(t.transcribe(self.wav), "Email the professor about the poster.")
        cmd, kwargs = self.calls[0]
        self.assertEqual(cmd, ["whisper-cli", "-m", "/models/base.bin", "-f", str(self.wav),
                               "-nt", "--no-prints"])
        self.assertEqual(kwargs["timeout"], 90)

    def test_missing_or_tiny_file_is_empty(self):
        # E-01
        t = self.transcriber(stdout="should not run")
        self.assertEqual(t.transcribe(self.wav), "")
        self.wav.write_bytes(b"\0" * (MIN_WAV_BYTES - 1))
        self.assertEqual(t.transcribe(self.wav), "")
        self.assertEqual(self.calls, [])

    def test_timeout_and_missing_binary_are_empty(self):
        # E-06, E-07
        self.wav.write_bytes(b"\0" * MIN_WAV_BYTES)
        for exc in (subprocess.TimeoutExpired("whisper-cli", 90), FileNotFoundError("whisper-cli")):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(self.transcriber(exc=exc).transcribe(self.wav), "")
        self.assertIn("[whisper] failed", self.log.text())

    def test_problems_reported_at_startup(self):
        problems = self.transcriber().problems()
        self.assertEqual(len(problems), 2)
        self.assertIn("whisper-cli not found", problems[0])
        self.assertIn("TASKLOT_WHISPER_MODEL", problems[1])


class ScriptTranscriberTest(unittest.TestCase):
    """The offline CLI's transcriber raises with a user-facing message."""

    def test_unset_script(self):
        with self.assertRaises(TranscriptionError) as ctx:
            ScriptTranscriber("", log=silent).transcribe(Path("memo.m4a"))
        self.assertIn("TASKLOT_WHISPER_SCRIPT", str(ctx.exception))

    def test_runs_script_and_reports_failure(self):
        with tempfile.NamedTemporaryFile(suffix=".py") as script:
            ok = ScriptTranscriber(script.name, log=silent, runner=lambda cmd, **kw:
                                   subprocess.CompletedProcess(cmd, 0, stdout=" call mom \n", stderr=""))
            self.assertEqual(ok.transcribe(Path("memo.m4a")), "call mom")
            bad = ScriptTranscriber(script.name, log=silent, runner=lambda cmd, **kw:
                                    subprocess.CompletedProcess(cmd, 2, stdout="", stderr="no model"))
            with self.assertRaises(TranscriptionError) as ctx:
                bad.transcribe(Path("memo.m4a"))
            self.assertIn("no model", str(ctx.exception))


class FakeTranscriberTest(unittest.TestCase):
    """The fake returns its text for any path."""

    def test_fixed_text(self):
        self.assertEqual(FakeTranscriber("call mom", log=silent).transcribe(Path("x")), "call mom")


if __name__ == "__main__":
    unittest.main()
