"""Tests for SerialLink with a fake port and a fake clock.

Covers DESIGN.md E-31 (pacing), E-35/E-39 (clear error when the port will not
open), E-36 (reconnect with backoff after a disconnect), E-37 (on_reconnect hook).
"""
import unittest

from tasklot.logs import LogCapture, silent
from tasklot.serial_link import RECONNECT_BACKOFF_S, SerialLink, SerialLinkError
from tests.fakes import FakeClock, FakePort, PortFactory

PACING = 0.35


def make_link(*outcomes, clock=None, log=silent, **kwargs):
    """A SerialLink on fake ports and a fake clock; returns (link, factory, clock)."""
    clock = clock or FakeClock()
    factory = PortFactory(*outcomes)
    link = SerialLink("/dev/fake", serial_factory=factory, pacing=PACING, reset_delay=3.0,
                      clock=clock, sleep=clock.sleep, log=log, **kwargs)
    return link, factory, clock


class OpenTest(unittest.TestCase):
    """Opening waits out the board reset; failures name TASKLOT_PORT."""

    def test_open_waits_for_reset(self):
        port = FakePort()
        link, factory, clock = make_link(port)
        link.open()
        self.assertTrue(link.connected)
        self.assertEqual(factory.calls, [("/dev/fake", 9600, 1.0)])
        self.assertEqual(clock.sleeps, [3.0])

    def test_open_failure_is_clear(self):
        link, _, _ = make_link(OSError("[Errno 16] Resource busy"))
        with self.assertRaises(SerialLinkError) as ctx:
            link.open()
        message = str(ctx.exception)
        self.assertIn("TASKLOT_PORT", message)
        self.assertIn("Only one program can hold the port", message)


class SendTest(unittest.TestCase):
    """Wire format and pacing."""

    def test_wire_bytes(self):
        clock = FakeClock()
        port = FakePort(clock=clock)
        link, _, _ = make_link(port, clock=clock)
        link.open()
        link.send("CAR 3 Email the Prof")
        link.send("CAR 4 caf\u00e9 run")
        self.assertEqual(port.writes, [b"CAR 3 Email the Prof\n", b"CAR 4 caf run\n"])

    def test_never_two_writes_inside_pacing_window(self):
        # E-31
        clock = FakeClock()
        port = FakePort(clock=clock)
        link, _, _ = make_link(port, clock=clock)
        link.open()
        for i in range(6):
            link.send(f"CAR {i + 1} task")
            clock.advance(0.1 * (i % 3))  # irregular gaps, some shorter than the pacing
        gaps = [b - a for a, b in zip(port.write_times, port.write_times[1:])]
        self.assertEqual(len(gaps), 5)
        for gap in gaps:
            self.assertGreaterEqual(gap, PACING - 1e-9)

    def test_no_wait_when_already_spaced(self):
        clock = FakeClock()
        port = FakePort(clock=clock)
        link, _, _ = make_link(port, clock=clock)
        link.open()
        link.send("PING")
        clock.advance(5)
        sleeps_before = len(clock.sleeps)
        link.send("PING")
        self.assertEqual(len(clock.sleeps), sleeps_before)

    def test_write_failure_is_logged_not_raised(self):
        log = LogCapture()
        link, _, _ = make_link(FakePort(fail_writes=True), log=log)
        link.open()
        self.assertFalse(link.send("LOT"))
        self.assertIn("write failed", log.text())

    def test_send_while_closed_is_dropped(self):
        log = LogCapture()
        link, _, _ = make_link(log=log)
        self.assertFalse(link.send("LOT"))
        self.assertIn("not connected", log.text())

    def test_long_line_warns(self):
        log = LogCapture()
        link, _, _ = make_link(FakePort(), log=log)
        link.open()
        link.send("CAR 1 " + "x" * 60)
        self.assertIn("the board keeps 47", log.text())


class ReadTest(unittest.TestCase):
    """Reading, decoding, and reconnecting."""

    def test_lines_are_decoded_and_stripped(self):
        link, _, _ = make_link(FakePort([b"SPEAKER  CAR 3 ordering\r\n", b"\xff\r\n"]))
        link.open()
        self.assertEqual(link.readline(), "SPEAKER  CAR 3 ordering")
        self.assertEqual(link.readline(), "\ufffd")
        self.assertEqual(link.readline(), "")

    def test_disconnect_reconnects_with_backoff(self):
        # E-36: the dead handle is closed, reopen is retried with backoff,
        # the state change is logged once each way, and E-37's hook fires.
        dead = FakePort(fail_reads_after=0)
        fresh = FakePort([b"PONG\r\n"])
        calls = []
        log = LogCapture()
        link, factory, clock = make_link(dead, OSError("gone"), OSError("gone"), fresh,
                                         log=log, on_reconnect=lambda: calls.append("hook"))
        link.open()
        self.assertIsNone(link.readline())
        self.assertTrue(dead.closed)
        self.assertEqual(len(factory.calls), 4)
        self.assertEqual(clock.sleeps, [3.0, RECONNECT_BACKOFF_S[0], RECONNECT_BACKOFF_S[1],
                                        RECONNECT_BACKOFF_S[2], 3.0])
        self.assertEqual(calls, ["hook"])
        self.assertEqual(sum("lost the board" in l for l in log.lines), 1)
        self.assertEqual(sum("reconnected" in l for l in log.lines), 1)
        self.assertEqual(link.readline(), "PONG")

    def test_read_for_collects_lines(self):
        clock = FakeClock()
        port = FakePort([b"--------------------\r\n", b"1>-\r\n"])
        link, _, _ = make_link(port, clock=clock)
        link.open()
        # FakePort returns instantly, so advance time on every empty read.
        original = port.readline

        def readline():
            clock.advance(0.5)
            return original()
        port.readline = readline
        self.assertEqual(link.read_for(2.0), ["--------------------", "1>-"])


if __name__ == "__main__":
    unittest.main()
