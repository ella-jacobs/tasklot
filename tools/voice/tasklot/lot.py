"""Lot: the laptop's model of the parking lot.

Holds what the laptop knows about each car (its full task and the label the
board is showing), which car sits in which space (space order is priority
order), and the order currently being recorded. Pure state: no I/O except the
explicit load()/save() of tasks.json for the offline CLI.

Order ids are the guard against stale results. Every new order and every
pickup bumps the car's order id; transcription and LLM results carry the id
they were started under, and Ears drops any result whose id is no longer
current (DESIGN.md E-12, E-13).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .config import MAX_CARS, SPACES
from .task import Task

LotRow = Union[Task, str, None]  # what one LCD row shows: a task, a label, or empty


class LotFull(Exception):
    """Every car number already has a task."""


class Lot:
    """Cars, their tasks and labels, the four spaces, and the open order.

    Args:
        max_cars: highest car number (firmware MAX_CARS).
        spaces: number of parking spaces (LCD rows).

    Attributes:
        tasks: car -> Task, only for tasks the laptop produced or loaded.
        labels: car -> the label the board is showing.
        spaces: index i holds the car parked in space i + 1, or None.
        recording: the car whose order is being recorded, or None.
        updated: when the store was last saved (tasks.json "updated"), or "".
    """

    def __init__(self, max_cars: int = MAX_CARS, spaces: int = SPACES):
        self.max_cars = max_cars
        self.tasks: dict[int, Task] = {}
        self.labels: dict[int, str] = {}
        self.spaces: list[Optional[int]] = [None] * spaces
        self.recording: Optional[int] = None
        self.updated = ""
        self._order_ids: dict[int, int] = {}

    # -- orders ---------------------------------------------------------------
    def begin_order(self, car: int) -> int:
        """Start recording an order for `car`, replacing any open order.

        Returns:
            int: the new order id for this car.
        """
        self.recording = car
        return self._bump(car)

    def close_order(self) -> Optional[tuple[int, int]]:
        """End the open order, if any, keeping its id current.

        Returns:
            (car, order_id) of the order that was open, or None.
        """
        if self.recording is None:
            return None
        car = self.recording
        self.recording = None
        return car, self.order_id(car)

    def order_id(self, car: int) -> int:
        """The car's current order id (0 if it never ordered)."""
        return self._order_ids.get(car, 0)

    def is_current(self, car: int, order_id: int) -> bool:
        """True if `order_id` is still the car's latest order, i.e. the car was
        not collected and did not order again since the result was started."""
        return self.order_id(car) == order_id

    def _bump(self, car: int) -> int:
        """Advance the car's order id, invalidating results started under the old one."""
        self._order_ids[car] = self.order_id(car) + 1
        return self._order_ids[car]

    # -- tasks and labels -----------------------------------------------------
    def set_task(self, task: Task) -> None:
        """Store `task` as its car's full task (does not change the label)."""
        self.tasks[task.car] = task

    def set_label(self, car: int, label: str) -> None:
        """Record the label the board shows for `car`; "" means blank (forgotten)."""
        if label:
            self.labels[car] = label
        else:
            self.labels.pop(car, None)

    def label(self, car: int) -> str:
        """The label for `car`: what the board echoed, else the task's lcd, else ""."""
        if car in self.labels:
            return self.labels[car]
        task = self.tasks.get(car)
        return task.lcd if task else ""

    def full_text(self, car: int) -> str:
        """Text for a read-back: the full task if the laptop has it, else the label."""
        task = self.tasks.get(car)
        return (task.full if task else "") or self.labels.get(car, "")

    def collect(self, car: int) -> None:
        """The car went through the pickup lane: forget its task and label, free
        its space, close its order, and invalidate any result still in flight."""
        self.tasks.pop(car, None)
        self.labels.pop(car, None)
        self._release(car)
        if self.recording == car:
            self.recording = None
        self._bump(car)

    def clear(self) -> None:
        """Forget every task and label (the RESET command). Spaces are kept,
        because the cars are physically still parked."""
        self.tasks.clear()
        self.labels.clear()

    def next_free_car(self) -> int:
        """The lowest car number without a task.

        Raises:
            LotFull: all max_cars cars have tasks.
        """
        for car in range(1, self.max_cars + 1):
            if car not in self.tasks:
                return car
        raise LotFull(f"All {self.max_cars} cars have tasks.")

    # -- spaces ---------------------------------------------------------------
    def park(self, space: int, car: int) -> None:
        """`car` arrived on `space` (1-based). A car is in one space at a time,
        so moving it releases its old space (E-26).

        Raises:
            ValueError: space is out of range.
        """
        index = self._space_index(space)
        self._release(car)
        self.spaces[index] = car

    def leave(self, space: int, car: int) -> None:
        """`car` left `space`. Ignored if another car has since parked there.

        Raises:
            ValueError: space is out of range.
        """
        index = self._space_index(space)
        if self.spaces[index] == car:
            self.spaces[index] = None

    def space_of(self, car: int) -> Optional[int]:
        """The 1-based space `car` is parked in, or None."""
        for i, parked in enumerate(self.spaces):
            if parked == car:
                return i + 1
        return None

    def rows(self, order: Optional[list[int]] = None) -> list[LotRow]:
        """What each LCD row shows, top (priority 1) to bottom.

        Args:
            order: car numbers to show in spaces 1..n, for previewing without a
                board (the offline CLI uses cars 1-4). None uses the parked cars.

        Returns:
            list: per row, the label the board shows for the car, else its Task,
            else "CAR n" for a parked car the laptop knows nothing about (as the
            firmware shows), else None for an empty space. The label comes
            first for the same reason as in label(): after an LLM upgrade it is
            what the board displays. With `order`, a car without a task is None,
            as the original preview printed it.
        """
        if order is not None:
            return [self.tasks.get(car) for car in order]
        out: list[LotRow] = []
        for car in self.spaces:
            if car is None:
                out.append(None)
            else:
                out.append(self.labels.get(car) or self.tasks.get(car) or f"CAR {car}")
        return out

    def _space_index(self, space: int) -> int:
        """0-based index of a 1-based space. Raises ValueError if out of range."""
        if not 1 <= space <= len(self.spaces):
            raise ValueError(f"space {space} is not 1..{len(self.spaces)}")
        return space - 1

    def _release(self, car: int) -> None:
        """Empty whichever space holds `car`."""
        for i, parked in enumerate(self.spaces):
            if parked == car:
                self.spaces[i] = None

    # -- tasks.json -----------------------------------------------------------
    def to_dict(self) -> dict:
        """The tasks.json document: {"updated": str, "cars": {"<n>": {...}}}."""
        return {"updated": self.updated,
                "cars": {str(car): self.tasks[car].to_dict() for car in sorted(self.tasks)}}

    @classmethod
    def from_dict(cls, data: dict, max_cars: int = MAX_CARS) -> "Lot":
        """Rebuild a Lot from a tasks.json document.

        Raises:
            ValueError, KeyError, TypeError: the document is malformed.
        """
        lot = cls(max_cars=max_cars)
        lot.updated = data.get("updated", "")
        for key, entry in data.get("cars", {}).items():
            car = int(key)
            lot.tasks[car] = Task.from_dict(car, entry)
        return lot

    @classmethod
    def load(cls, path: Path, max_cars: int = MAX_CARS) -> tuple["Lot", bool]:
        """Load tasks.json; a missing or unreadable file gives an empty Lot.

        Returns:
            (lot, ok): ok is False when the file existed but could not be read,
            so the caller can say it is starting fresh.
        """
        path = Path(path)
        if not path.exists():
            return cls(max_cars=max_cars), True
        try:
            with path.open(encoding="utf-8") as f:
                return cls.from_dict(json.load(f), max_cars=max_cars), True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls(max_cars=max_cars), False

    def save(self, path: Path, now: Optional[datetime] = None) -> Path:
        """Write tasks.json, stamping "updated".

        Args:
            path: destination file.
            now: timestamp to record; None means the current time.

        Returns:
            Path: where it was written.

        Raises:
            OSError: the file cannot be written.
        """
        path = Path(path)
        self.updated = (now or datetime.now()).isoformat(timespec="seconds")
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path
