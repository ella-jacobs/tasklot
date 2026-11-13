"""Tests for Recorder, NullRecorder, and the transcribers, with every subprocess
replaced by a fake.

Covers DESIGN.md E-01 (empty recording), E-03 (minimum hold before stopping),
E-04 (stop escalation), E-05 (failed start never yields a stale file), E-06
(startup check), E-07 (whisper timeout).
"""
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

from tasklot.logs import LogCapture, silent
from tasklot.recorder import NullRecorder, Recorder, wav_name
from tasklot.transcriber import (
    MIN_WAV_BYTES, FakeTranscriber, ScriptTranscriber, Transcriber, TranscriptionError,
)
from tests.fakes import FakeClock, FakeProcess


class RecorderTestCase(unittest.TestCase):
    """Shared temp directory and fake clock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = FakeClock()
        self.log = LogCapture()

    def tearDown(self):
        self.tmp.cleanup()

    def recorder(self, *processes):
        """A Recorder whose factory returns the given FakeProcesses (or raises)."""
        self.launched = []
        queue = list(processes)

        def factory(cmd, **kwargs):
            self.launched.append(cmd)
            proc = queue.pop(0)
            if isinstance(proc, Exception):
                raise proc
            return proc
        return Recorder(self.dir, ":0", process_factory=factory, clock=self.clock,
                        sleep=self.clock.sleep, min_hold=0.6, log=self.log)


class RecorderStartStopTest(RecorderTestCase):
    """The ffmpeg command, file naming, and the stop sequence."""

    def test_command_and_unique_path(self):
        path = self.dir / wav_name(3, 1)
        rec = self.recorder(FakeProcess(writes_file=path))
        self.assertEqual(rec.start(3, 1), path)
        self.assertEqual(self.launched[0], ["ffmpeg", "-y", "-f", "avfoundation", "-i", ":0",
                                            "-ar", "16000", "-ac", "1", str(path)])
        self.assertNotEqual(wav_name(3, 1), wav_name(3, 2))

    def test_graceful_stop_returns_file(self):
        path = self.dir / wav_name(3, 1)
        proc = FakeProcess(writes_file=path)
        rec = self.recorder(proc)
        rec.start(3, 1)
        self.clock.advance(5)
        self.assertEqual(rec.stop(), path)
        self.assertEqual(proc.events, ["communicate b'q'"])
        self.assertFalse(rec.is_running())

    def test_min_hold_waits_without_real_sleep(self):
        # E-03: parked 0.2 s after ordering -> wait the remaining 0.4 s first.
        rec = self.recorder(FakeProcess(writes_file=self.dir / wav_name(1, 1)))
        rec.start(1, 1)
        self.clock.advance(0.2)
        rec.stop()
        self.assertAlmostEqual(self.clock.sleeps[-1], 0.4)

    def test_escalates_to_sigint(self):
        # E-04
        proc = FakeProcess(on_q="hang", writes_file=self.dir / wav_name(1, 1))
        rec = self.recorder(proc)
        rec.start(1, 1)
        self.clock.advance(5)
        self.assertIsNotNone(rec.stop())
        self.assertEqual(proc.events, ["communicate b'q'", f"signal {int(signal.SIGINT)}", "wait"])

    def test_escalates_to_kill_and_logs(self):
        # E-04: the last resort leaves no usable file here.
        proc = FakeProcess(on_q="hang", on_sigint="hang")
        rec = self.recorder(proc)
        rec.start(1, 1)
        self.clock.advance(5)
        self.assertIsNone(rec.stop())
        self.assertIn("kill", proc.events)
        self.assertIn("SIGKILL", self.log.text())

    def test_failed_start_never_returns_stale_file(self):
        # E-05: a leftover WAV from an earlier run must not become this order.
        stale = self.dir / wav_name(2, 1)
        stale.write_bytes(b"old audio" * 2000)
        rec = self.recorder(FileNotFoundError("ffmpeg"))
        self.assertIsNone(rec.start(2, 1))
        self.assertFalse(stale.exists())
        self.assertIsNone(rec.stop())
        self.assertIn("FAILED to start ffmpeg", self.log.text())

    def test_stop_without_start(self):
        self.assertIsNone(self.recorder().stop())

    def test_discard_deletes_file(self):
        path = self.dir / wav_name(4, 1)
        rec = self.recorder(FakeProcess(writes_file=path))
        rec.start(4, 1)
        self.clock.advance(1)
        rec.discard()
        self.assertFalse(path.exists())

    def test_elapsed(self):
        rec = self.recorder(FakeProcess())
        self.assertEqual(rec.elapsed(), 0.0)
        rec.start(1, 1)
        self.clock.advance(12)
        self.assertEqual(rec.elapsed(), 12)


class NullRecorderTest(unittest.TestCase):
    """NullRecorder tracks state like a Recorder but starts nothing."""

    def test_lifecycle(self):
        clock = FakeClock()
        rec = NullRecorder(Path("/nowhere"), log=silent, clock=clock)
        self.assertFalse(rec.is_running())
        path = rec.start(5, 2)
        clock.advance(3)
        self.assertTrue(rec.is_running())
        self.assertEqual(rec.elapsed(), 3)
        self.assertEqual(rec.stop(), path)
        self.assertIsNone(rec.stop())


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
