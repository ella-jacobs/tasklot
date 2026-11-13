"""Tests for the serial protocol: event parsing and exact command strings.

Covers DESIGN.md E-16 (read-back chunking), E-17 (ASCII on the wire), E-32
(garbage never raises), E-33 (anchored patterns), and every event in section 3.1.
"""
import unittest

from tasklot import protocol as P
from tasklot.protocol import (
    Collected, Left, NewCar, Ordering, Parked, Playback, Pong, TaskEcho, Unknown, parse_line,
)


class ParseEventsTest(unittest.TestCase):
    """Every event line exactly as the firmware prints it (note the spacing)."""

    def test_events(self):
        cases = [
            ("SPEAKER  CAR 3 ordering", Ordering(3)),
            ("PLAYBACK CAR 3 reading back", Playback(3)),
            ("SPACE 2  <- CAR 3 parked", Parked(2, 3)),
            ("SPACE 2  -> CAR 3 left", Left(2, 3)),
            ("PICKUP   CAR 3 collected", Collected(3)),
            ("TASK 3 Email the Prof", TaskEcho(3, "Email the Prof")),
            ("TASK 3 ", TaskEcho(3, "")),
            ("TASK 3", TaskEcho(3, "")),
            ("* NEW CAR registered -> CAR 2   UID 04 D1 60 7A 2B 11 90 ", NewCar(2, "04 D1 60 7A 2B 11 90")),
            ("PONG", Pong()),
        ]
        for line, want in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_line(line), want)
                self.assertEqual(parse_line(line + "\r\n"), want)

    def test_lot_printout_and_banner_are_unknown(self):
        for line in ("--------------------", "1>Email the Prof", "2>-", "3>CAR 4",
                     "=== TaskLot v2 - four spaces, a speaker, a pickup lane ===",
                     "* tasks cleared", "* bad car number: 9", "LCD: 0x27"):
            with self.subTest(line=line):
                self.assertIsInstance(parse_line(line), Unknown)


class GarbageTest(unittest.TestCase):
    """E-32: merged, partial, and empty lines are Unknown, never an exception."""

    def test_garbage(self):
        for line in ("3>Charge baCAR 4 Glu", "", "   ", "\x00\xff", "SPEAKER CAR x ordering",
                     "SPACE <- CAR 3 parked", "CAR 3 reading"):
            with self.subTest(line=line):
                self.assertIsInstance(parse_line(line), Unknown)


class AnchoringTest(unittest.TestCase):
    """E-33: event text inside a label or lot line does not trigger the event."""

    def test_label_containing_event_text(self):
        # "CAR 9 reading back" is exactly 18 characters, a legal label.
        self.assertEqual(parse_line("TASK 3 CAR 9 reading back"), TaskEcho(3, "CAR 9 reading back"))
        self.assertIsInstance(parse_line("1>CAR 9 reading back"), Unknown)
        self.assertIsInstance(parse_line("2>PICKUP CAR 1 collected"), Unknown)


class CommandFormatTest(unittest.TestCase):
    """Command strings are byte-identical to what the pre-refactor daemon sent."""

    def test_simple_commands(self):
        self.assertEqual(P.car_command(3, "Email the Prof"), "CAR 3 Email the Prof")
        self.assertEqual(P.done_command(4), "DONE 4")
        self.assertEqual((P.CLEAR, P.LOT, P.PING, P.FULLCLR), ("CLEAR", "LOT", "PING", "FULLCLR"))

    def test_encode_is_ascii_with_newline(self):
        self.assertEqual(P.encode("CAR 1 caf\u00e9"), b"CAR 1 caf\n")
        self.assertEqual(P.encode("LOT"), b"LOT\n")

    def test_read_back_sequence_matches_original(self):
        # Captured from the pre-refactor daemon in the end-to-end test.
        self.assertEqual(P.full_text_commands(3, "Email the professor about the final project"),
                         ["FULLCLR", "FULL Email the professor about the final",
                          "FULL project", "FULLSHOW 3"])


class ChunkTest(unittest.TestCase):
    """E-16: chunks never exceed 40 characters, even for one huge word."""

    def test_word_boundaries(self):
        text = "one two three four five six seven eight nine ten eleven twelve"
        chunks = P.chunk_text(text)
        self.assertEqual(" ".join(chunks), text)
        self.assertTrue(all(len(c) <= P.FULL_CHUNK_MAX for c in chunks))

    def test_oversized_word_is_split(self):
        word = "x" * 95
        chunks = P.chunk_text("start " + word + " end")
        self.assertEqual(chunks, ["start", "x" * 40, "x" * 40, "x" * 15 + " end"])
        for cmd in P.full_text_commands(1, "start " + word):
            self.assertLessEqual(len(cmd), P.BOARD_LINE_MAX)

    def test_exactly_forty_has_no_empty_chunk(self):
        self.assertEqual(P.chunk_text("y" * 40), ["y" * 40])

    def test_empty(self):
        self.assertEqual(P.chunk_text("   "), [])
        self.assertEqual(P.full_text_commands(2, ""), ["FULLCLR", "FULLSHOW 2"])


if __name__ == "__main__":
    unittest.main()
