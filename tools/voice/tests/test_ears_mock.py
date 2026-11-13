"""End-to-end test: the ears daemon against a fake board on a pseudo-terminal.

Starts `tasklot_ears.py` as a real subprocess pointed at one end of a pty, plays
the board's exact serial lines into the other end, and checks the bytes the
daemon writes back. Transcription is faked with TASKLOT_FAKE_TRANSCRIPT and the
LLM is turned off, so no microphone, model, or network is involved. The daemon's
side-channel files and recordings go to a temporary directory, so the test never
touches the tasklot_* files a real running daemon would use.

Skipped (not failed) when pyserial is not installed, because the daemon needs it
to open the port.
"""
import importlib.util
import os
import pty
import select
import subprocess
import sys
import tempfile
import termios
import time
import unittest

VOICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EARS_SCRIPT = os.path.join(VOICE_DIR, "tasklot_ears.py")
HAVE_PYSERIAL = importlib.util.find_spec("serial") is not None

FAKE_TRANSCRIPT = "email the professor about the final project"

# What the v2 firmware prints at boot, trimmed to the lines a parser could trip on.
BOOT_LINES = [
    "=== TaskLot v2 - four spaces, a speaker, a pickup lane ===",
    "space 1 reader (SS 44): 0x92   ok - genuine",
    "speaker reader (SS 37): 0x92   ok - genuine",
    "pickup  reader (SS 36): 0x92   ok - genuine",
    "LCD: 0x27",
    "--------------------", "1>-", "2>-", "3>-", "4>-", "--------------------",
]

# Every byte the daemon wrote for the scenario below, captured from the code as
# imported (before the refactor). The serial protocol must not change.
EXPECTED_WIRE = (
    "CAR 3 Email the Prof\n"
    "FULLCLR\n"
    "FULL Email the professor about the final\n"
    "FULL project\n"
    "FULLSHOW 3\n"
    "CAR 2 Email the Prof\n"
)

# Seconds to wait for the daemon to open the port before the board "boots".
# The daemon waits for the Mega's DTR reset after opening; the test shortens
# that wait through TASKLOT_RESET_DELAY.
STARTUP_WAIT_S = 2.0


@unittest.skipUnless(HAVE_PYSERIAL, "pyserial not installed (make test PYTHON=.venv/bin/python)")
class EarsAgainstFakeBoardTest(unittest.TestCase):
    """One scripted session covering order, read-back, stray park, pickup, garbage."""

    def setUp(self):
        self.master, slave = pty.openpty()
        # Echo off, or the pty parrots our own writes back and the capture looks
        # like the daemon replied when it never did.
        attrs = termios.tcgetattr(slave)
        attrs[3] = attrs[3] & ~termios.ECHO & ~termios.ECHONL & ~termios.ICANON
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        self.slave = slave
        self.scratch = tempfile.TemporaryDirectory()
        env = dict(os.environ,
                   TASKLOT_PORT=os.ttyname(slave),
                   TASKLOT_FAKE_TRANSCRIPT=FAKE_TRANSCRIPT,
                   TASKLOT_LLM="0",
                   TASKLOT_RESET_DELAY="0.5",
                   TASKLOT_REC_DIR=self.scratch.name,
                   TASKLOT_SAY_FILE=os.path.join(self.scratch.name, "say.txt"),
                   TASKLOT_CMD_FILE=os.path.join(self.scratch.name, "cmd.txt"))
        self.proc = subprocess.Popen([sys.executable, EARS_SCRIPT], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True)
        self.captured = []
        time.sleep(STARTUP_WAIT_S)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.communicate()
        os.close(self.master)
        os.close(self.slave)
        self.scratch.cleanup()

    def board_says(self, line, wait):
        """Write one board line (with the firmware's CRLF) and collect replies.

        Args:
            line: the exact text the firmware would print.
            wait: seconds to let the daemon react before draining.
        """
        os.write(self.master, (line + "\r\n").encode())
        time.sleep(wait)
        self.drain()

    def drain(self):
        """Append everything the daemon has written so far to self.captured."""
        while select.select([self.master], [], [], 0.15)[0]:
            try:
                data = os.read(self.master, 4096).decode(errors="replace")
            except OSError:
                return
            if data:
                self.captured.append(data)

    def test_scripted_session_writes_exact_protocol(self):
        for line in BOOT_LINES:
            self.board_says(line, 0.05)
        # 1. blank car orders, then parks -> one CAR command
        self.board_says("SPEAKER  CAR 3 ordering", 1.0)
        self.board_says("SPACE 2  <- CAR 3 parked", 3.0)
        # 2. loaded car returns to the speaker -> FULL* read-back
        self.board_says("PLAYBACK CAR 3 reading back", 2.5)
        # 3. a park with no recording open must send nothing
        self.board_says("SPACE 4  <- CAR 1 parked", 1.0)
        # 4. pickup forgets the task, so a read-back has nothing to show
        self.board_says("PICKUP   CAR 3 collected", 0.5)
        self.board_says("PLAYBACK CAR 3 reading back", 1.0)
        # 5. garbage and empty lines must not kill the read loop
        self.board_says("3>Charge baCAR 4 Glu", 0.3)
        self.board_says("", 0.3)
        self.board_says("SPEAKER  CAR 2 ordering", 0.8)
        self.board_says("SPACE 1  <- CAR 2 parked", 3.0)
        time.sleep(0.5)
        self.drain()
        self.assertEqual("".join(self.captured), EXPECTED_WIRE)
        # 6. SIGTERM stops the daemon the way Ctrl-C does, so shutdown() runs.
        self.proc.terminate()
        log = self.proc.communicate(timeout=5)[0]
        self.assertIn("[ears] stopped.", log)


if __name__ == "__main__":
    unittest.main()
