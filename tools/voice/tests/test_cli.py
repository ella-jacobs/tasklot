"""Tests for the offline tool and the command-line entry points.

The `voice` command must print exactly what the original tasklot_voice.py
printed (outputs pinned from the pre-refactor script) and write the same
tasks.json. --push is tested with a fake port and clock, and --watch with a
fake sleep, so nothing touches hardware or waits in real time.
"""
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tasklot import cli
from tasklot.config import MAX_CARS, Settings
from tasklot.offline import OfflineError, OfflineTool
from tasklot.serial_link import SerialLink
from tasklot.logs import silent
from tests.fakes import FakeClock, FakePort, PortFactory

VOICE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_TIMEOUT_S = 30   # a script that hangs (a watcher that never exits) fails, not stalls

# Pinned from the pre-refactor tasklot_voice.py (the "saved" path line differs per run).
FIRST_RUN = """
  CAR 1
  full : Charge the battery pack
  lcd  : Charge battry pack  (18/18)
  due  : tonight

   +--------------------+
   |1>Charge battry pack|
   |2>-                 |
   |3>-                 |
   |4>-                 |
   +--------------------+

"""
SECOND_RUN = """
  CAR 3
  full : Email the professor about whether we still need the poster
  lcd  : Email the Prof      (14/18)
  due  : friday

   +--------------------+
   |1>Charge battry pack|
   |2>-                 |
   |3>Email the Prof    |
   |4>-                 |
   +--------------------+

"""


class StubTranscriber:
    """Returns a fixed transcript per file name."""

    def __init__(self, texts):
        self.texts = texts

    def transcribe(self, path):
        return self.texts[Path(path).name]


class OfflineTestCase(unittest.TestCase):
    """A temp tasks.json and captured output streams."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.settings = Settings(tasks_file=self.dir / "tasks.json", reset_delay=3.0)
        self.out, self.err = io.StringIO(), io.StringIO()

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, transcriber=None, **kwargs):
        return OfflineTool(self.settings, transcriber or StubTranscriber({}),
                           out=self.out, err=self.err, **kwargs)


class AddTest(OfflineTestCase):
    """Adding tasks, next free car, full lot, empty input."""

    def test_add_and_preview_match_original_output(self):
        tool = self.tool()
        tool.add("remind me to charge the battery pack tonight", None, "typed")
        tool.preview()
        self.assertEqual(self.out.getvalue(), FIRST_RUN)

    def test_next_free_car_and_full_lot(self):
        tool = self.tool()
        for i in range(MAX_CARS):
            self.assertEqual(tool.add(f"call person number {i}", None, "typed").car, i + 1)
        with self.assertRaises(OfflineError) as ctx:
            tool.add("one more task")
        self.assertIn("Pass --car N", str(ctx.exception))
        self.assertEqual(tool.add("overwrite the first", 1).car, 1)

    def test_empty_input_is_skipped(self):
        tool = self.tool()
        self.assertIsNone(tool.add("  ...  "))
        self.assertIn("nothing usable", self.err.getvalue())
        self.assertFalse(tool.has_tasks)

    def test_unreadable_store_starts_fresh(self):
        self.settings.tasks_file.write_text("{broken")
        tool = self.tool()
        self.assertIn("unreadable, starting fresh", self.err.getvalue())
        self.assertFalse(tool.has_tasks)


class PushTest(OfflineTestCase):
    """--push uses the paced SerialLink (E-31) and the exact command strings."""

    def test_push_sends_labels_then_lot(self):
        clock = FakeClock()
        port = FakePort([b"--------------------\r\n", b"1>Charge battry pack\r\n"], clock=clock)
        original = port.readline

        def readline():
            clock.advance(0.2)
            return original()
        port.readline = readline
        factory = PortFactory(port)
        tool = self.tool(link_factory=lambda p: SerialLink(p, serial_factory=factory, clock=clock,
                                                           sleep=clock.sleep, log=silent))
        tool.add("remind me to charge the battery pack tonight", 1, "typed")
        tool.add("call mom", 3, "typed")
        reply = tool.push("/dev/fake")
        self.assertEqual(port.wire(), "CAR 1 Charge battry pack\nCAR 3 Call mom\nLOT\n")
        self.assertTrue(port.input_reset)
        self.assertTrue(port.closed)
        self.assertEqual(reply, ["--------------------", "1>Charge battry pack"])
        gaps = [b - a for a, b in zip(port.write_times, port.write_times[1:])]
        self.assertTrue(all(g >= 0.35 - 1e-9 for g in gaps))
        self.assertIn("-> CAR 3 Call mom", self.err.getvalue())


class WatchTest(OfflineTestCase):
    """--watch ignores existing files and adds new ones."""

    def test_watch_adds_new_recordings(self):
        inbox = self.dir / "inbox"
        inbox.mkdir()
        (inbox / "old.m4a").write_bytes(b"x")
        (inbox / "notes.txt").write_text("not audio")
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            if len(polls) == 1:
                (inbox / "new.m4a").write_bytes(b"audio")

        tool = self.tool(transcriber=StubTranscriber({"new.m4a": "call mom"}), sleep=sleep)
        tool.watch(inbox, max_polls=2)
        self.assertEqual(sorted(t.source for t in tool.lot.tasks.values()), ["new.m4a"])
        self.assertIn("1 file(s) already there", self.out.getvalue())

    def test_latest_memo(self):
        memos = self.dir / "memos"
        memos.mkdir()
        older, newer = memos / "a.m4a", memos / "b.m4a"
        older.write_bytes(b"1")
        newer.write_bytes(b"2")
        os.utime(older, (1, 1))
        self.assertEqual(OfflineTool.latest_memo(memos), newer)
        with self.assertRaises(OfflineError):
            OfflineTool.latest_memo(self.dir / "missing")


class CommandLineTest(unittest.TestCase):
    """The original scripts still run with the same flags and output."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, TASKLOT_TASKS_FILE=str(Path(self.tmp.name) / "tasks.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, *args], cwd=VOICE_DIR, env=self.env,
                              capture_output=True, text=True, timeout=SCRIPT_TIMEOUT_S)

    def test_tasklot_voice_text_runs_match_original(self):
        first = self.run_script("tasklot_voice.py", "--text", "remind me to charge the battery pack tonight")
        second = self.run_script("tasklot_voice.py", "--text",
                                 "Um okay so I really need to email the professor about whether we "
                                 "still need the poster by Friday", "--car", "3")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.rsplit("  saved ", 1)[0], FIRST_RUN)
        self.assertEqual(second.stdout.rsplit("  saved ", 1)[0], SECOND_RUN)
        with open(self.env["TASKLOT_TASKS_FILE"], encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)["cars"]), ["1", "3"])

    def test_module_entry_point_and_clear(self):
        result = self.run_script("-m", "tasklot", "voice", "--clear")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cleared", result.stdout)

    def test_push_without_port_fails_clearly(self):
        self.run_script("tasklot_voice.py", "--text", "call mom")
        result = self.run_script("tasklot_voice.py", "--push")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--push needs --port", result.stderr)

    def test_watch_push_without_port_fails_before_watching(self):
        # Without --port the watcher would run forever and never push.
        result = self.run_script("tasklot_voice.py", "--watch", self.tmp.name, "--push")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--push needs --port", result.stderr)

    def test_missing_transcriber_script_fails_clearly(self):
        self.env.pop("TASKLOT_WHISPER_SCRIPT", None)
        result = self.run_script("tasklot_voice.py", "memo.m4a")
        self.assertEqual(result.returncode, 1)
        self.assertIn("TASKLOT_WHISPER_SCRIPT", result.stderr)

    def test_ears_with_unopenable_port_exits_2(self):
        # E-35: a clear message and a non-zero exit, not a traceback.
        self.env["TASKLOT_PORT"] = str(Path(self.tmp.name) / "no-such-port")
        result = self.run_script("tasklot_ears.py")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[ears] !!", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class SigtermTest(unittest.TestCase):
    """SIGTERM is turned into the same KeyboardInterrupt path as Ctrl-C."""

    def test_handler_is_installed_and_raises_keyboard_interrupt(self):
        previous = cli.install_sigterm_handler()
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        handler = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)


if __name__ == "__main__":
    unittest.main()
