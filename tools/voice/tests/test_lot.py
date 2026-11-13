"""Tests for Lot and Task: spaces, priority order, order ids, and tasks.json.

Covers DESIGN.md E-24 (all four spaces full), E-25 (car limit), E-26 (car moved
between spaces), E-27 (swap), and the order-id guard behind E-12/E-13.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tasklot.condenser import Condenser
from tasklot.config import MAX_CARS
from tasklot.lot import Lot, LotFull
from tasklot.task import Task

STAMP = datetime(2026, 4, 1, 14, 3, 22)


def make_task(car, text):
    """A Task for `car` condensed from `text` with a fixed timestamp."""
    return Task.from_condensed(car, Condenser().condense(text), source="typed", recorded=STAMP)


class SpacesTest(unittest.TestCase):
    """Occupancy and priority order."""

    def test_rows_follow_space_order(self):
        lot = Lot()
        lot.set_task(make_task(3, "email the professor"))
        lot.set_label(5, "Call mom")
        lot.park(1, 5)
        lot.park(2, 3)
        lot.park(4, 7)  # parked, nothing known about it: shows as the firmware does
        rows = lot.rows()
        self.assertEqual(rows[0], "Call mom")
        self.assertEqual(rows[1].car, 3)
        self.assertIsNone(rows[2])
        self.assertEqual(rows[3], "CAR 7")
        self.assertEqual([r.strip() for r in Condenser.lot_lines(rows)],
                         ["1>Call mom", "2>Email the Prof", "3>-", "4>CAR 7"])

    def test_move_releases_old_space(self):
        # E-26: one car, one space; moving reorders, never duplicates.
        lot = Lot()
        lot.park(1, 2)
        lot.park(2, 2)
        self.assertEqual(lot.spaces, [None, 2, None, None])
        self.assertEqual(lot.space_of(2), 2)

    def test_swap_in_either_timing(self):
        # E-27: lifts report "left" first, or a car lands before its old space times out.
        slow = Lot()
        slow.park(1, 1); slow.park(2, 2)
        slow.leave(1, 1); slow.leave(2, 2)
        slow.park(1, 2); slow.park(2, 1)
        fast = Lot()
        fast.park(1, 1); fast.park(2, 2)
        fast.park(1, 2)          # car 2 lands on space 1 before space 2 timed out
        fast.park(2, 1)
        fast.leave(1, 1)         # stale "left" for car 1 on space 1: ignored
        fast.leave(2, 2)         # stale "left" for car 2 on space 2: ignored
        self.assertEqual(slow.spaces[:2], [2, 1])
        self.assertEqual(fast.spaces[:2], [2, 1])

    def test_all_four_full(self):
        # E-24: four cars, four rows of tasks; there is no fifth space.
        lot = Lot()
        for car in range(1, 5):
            lot.set_label(car, f"Task {car}")
            lot.park(car, car)
        self.assertEqual(lot.rows(), ["Task 1", "Task 2", "Task 3", "Task 4"])
        with self.assertRaises(ValueError):
            lot.park(5, 5)

    def test_leave_of_wrong_car_is_ignored(self):
        lot = Lot()
        lot.park(1, 2)
        lot.leave(1, 3)
        self.assertEqual(lot.spaces[0], 2)


class OrdersTest(unittest.TestCase):
    """Order ids invalidate results for collected or re-ordered cars."""

    def test_close_returns_open_order(self):
        lot = Lot()
        oid = lot.begin_order(3)
        self.assertEqual(lot.recording, 3)
        self.assertEqual(lot.close_order(), (3, oid))
        self.assertIsNone(lot.recording)
        self.assertIsNone(lot.close_order())
        self.assertTrue(lot.is_current(3, oid))

    def test_collect_invalidates(self):
        lot = Lot()
        oid = lot.begin_order(3)
        lot.close_order()
        lot.collect(3)
        self.assertFalse(lot.is_current(3, oid))

    def test_reorder_invalidates(self):
        lot = Lot()
        first = lot.begin_order(3)
        lot.close_order()
        second = lot.begin_order(3)
        self.assertFalse(lot.is_current(3, first))
        self.assertTrue(lot.is_current(3, second))

    def test_collect_forgets_everything(self):
        lot = Lot()
        lot.set_task(make_task(2, "call mom"))
        lot.set_label(2, "Call mom")
        lot.park(3, 2)
        lot.begin_order(2)
        lot.collect(2)
        self.assertEqual((lot.full_text(2), lot.label(2), lot.space_of(2), lot.recording),
                         ("", "", None, None))


class LabelsTest(unittest.TestCase):
    """Labels learned from the board versus full text produced here."""

    def test_full_text_prefers_task(self):
        lot = Lot()
        lot.set_label(1, "Email the Prof")
        self.assertEqual(lot.full_text(1), "Email the Prof")
        lot.set_task(make_task(1, "email the professor about the poster"))
        self.assertEqual(lot.full_text(1), "Email the professor about the poster")

    def test_empty_label_forgets(self):
        lot = Lot()
        lot.set_label(1, "x")
        lot.set_label(1, "")
        self.assertNotIn(1, lot.labels)

    def test_clear_keeps_spaces(self):
        lot = Lot()
        lot.set_label(1, "x")
        lot.park(1, 1)
        lot.clear()
        self.assertEqual((lot.labels, lot.spaces[0]), ({}, 1))


class NextFreeCarTest(unittest.TestCase):
    """E-25: car numbers run 1..MAX_CARS; a full lot raises."""

    def test_lowest_free(self):
        lot = Lot()
        lot.set_task(make_task(1, "a task"))
        lot.set_task(make_task(3, "a task"))
        self.assertEqual(lot.next_free_car(), 2)

    def test_full_lot_raises(self):
        lot = Lot()
        for car in range(1, MAX_CARS + 1):
            lot.set_task(make_task(car, "a task"))
        with self.assertRaises(LotFull):
            lot.next_free_car()


class TasksJsonTest(unittest.TestCase):
    """tasks.json keeps the original shape and round-trips."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "tasks.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        lot = Lot()
        lot.set_task(make_task(1, "remind me to charge the battery pack tonight"))
        lot.set_task(make_task(3, "call mom"))
        lot.save(self.path, now=STAMP)
        loaded, ok = Lot.load(self.path)
        self.assertTrue(ok)
        self.assertEqual(loaded.tasks, lot.tasks)
        self.assertEqual(loaded.updated, "2026-04-01T14:03:22")

    def test_file_shape_matches_original_tool(self):
        lot = Lot()
        lot.set_task(make_task(1, "remind me to charge the battery pack tonight"))
        lot.save(self.path, now=STAMP)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, {
            "updated": "2026-04-01T14:03:22",
            "cars": {"1": {"full": "Charge the battery pack", "lcd": "Charge battry pack",
                           "due": "tonight", "raw": "remind me to charge the battery pack tonight",
                           "source": "typed", "recorded": "2026-04-01T14:03:22"}}})
        self.assertEqual(list(data["cars"]["1"]), ["full", "lcd", "due", "raw", "source", "recorded"])

    def test_missing_file_is_empty(self):
        lot, ok = Lot.load(self.path)
        self.assertTrue(ok)
        self.assertEqual(lot.tasks, {})

    def test_unreadable_file_starts_fresh(self):
        for content in ("{not json", "[]", '{"cars": {"x": {}}}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                lot, ok = Lot.load(self.path)
                self.assertFalse(ok)
                self.assertEqual(lot.tasks, {})

    def test_entry_missing_fields_loads(self):
        self.path.write_text('{"cars": {"2": {"lcd": "Call mom"}}}', encoding="utf-8")
        lot, ok = Lot.load(self.path)
        self.assertTrue(ok)
        self.assertEqual(lot.tasks[2].lcd, "Call mom")
        self.assertIsNone(lot.tasks[2].recorded)

    def test_preview_order_matches_original(self):
        lot = Lot()
        lot.set_task(make_task(1, "remind me to charge the battery pack tonight"))
        lot.set_task(make_task(3, "Um okay so I really need to email the professor"))
        self.assertEqual(Condenser.lot_lines(lot.rows(order=[1, 2, 3, 4])),
                         ["1>Charge battry pack", "2>-                 ",
                          "3>Email the Prof    ", "4>-                 "])


if __name__ == "__main__":
    unittest.main()
