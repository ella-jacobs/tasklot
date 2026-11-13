"""Tests for Recorder and NullRecorder, with ffmpeg replaced by a fake process.

Covers DESIGN.md E-03 (minimum hold before stopping), E-04 (stop escalation),
and E-05 (failed start never yields a stale file).
"""
import signal
import tempfile
import unittest
from pathlib import Path

from tasklot.logs import LogCapture, silent
from tasklot.recorder import NullRecorder, Recorder, wav_name
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


if __name__ == "__main__":
    unittest.main()
