"""Task: one car's task as the laptop knows it.

The board only stores the 18-character label; the laptop keeps the full text so
a read-back can show the whole thing. Tasks are also what the offline CLI saves
to tasks.json, in the same per-car shape the original tool wrote:

    {"full": ..., "lcd": ..., "due": ..., "raw": ..., "source": ..., "recorded": ...}
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .condenser import Condensed

TIMESTAMP_SPEC = "seconds"  # tasks.json timestamps: 2026-04-01T14:03:22


@dataclass
class Task:
    """One task attached to one car.

    Attributes:
        car: 1-based car number as the board reports it.
        full: the whole task text.
        lcd: the label sent to the board (at most 18 characters).
        due: due hint from the Condenser, or "".
        raw: the transcript or typed text it came from.
        source: where it came from ("typed", an audio file name, "mic").
        recorded: when it was created, or None if unknown.
    """

    car: int
    full: str
    lcd: str
    due: str = ""
    raw: str = ""
    source: str = ""
    recorded: Optional[datetime] = None

    @classmethod
    def from_condensed(cls, car: int, condensed: Condensed, source: str = "",
                       recorded: Optional[datetime] = None) -> "Task":
        """Build a Task from Condenser output.

        Args:
            car: car number.
            condensed: the Condenser result.
            source: provenance label.
            recorded: timestamp; None means "now".
        """
        return cls(car=car, full=condensed.full, lcd=condensed.lcd, due=condensed.due,
                   raw=condensed.raw, source=source,
                   recorded=recorded or datetime.now().replace(microsecond=0))

    def to_dict(self) -> dict:
        """The tasks.json entry for this task (the car number is the dict key)."""
        return {
            "full": self.full,
            "lcd": self.lcd,
            "due": self.due,
            "raw": self.raw,
            "source": self.source,
            "recorded": self.recorded.isoformat(timespec=TIMESTAMP_SPEC) if self.recorded else "",
        }

    @classmethod
    def from_dict(cls, car: int, data: dict) -> "Task":
        """Rebuild a Task from a tasks.json entry; missing fields default to "".

        Args:
            car: the car number (the entry's key).
            data: the entry.

        Raises:
            ValueError: "recorded" is present but not an ISO timestamp.
        """
        stamp = data.get("recorded") or ""
        return cls(car=car, full=data.get("full", ""), lcd=data.get("lcd", ""),
                   due=data.get("due", ""), raw=data.get("raw", ""),
                   source=data.get("source", ""),
                   recorded=datetime.fromisoformat(stamp) if stamp else None)
