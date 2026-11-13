"""The one logging helper for the voice pipeline.

Every component logs short tagged lines ("[mic] recording for CAR 3") to stdout,
flushed immediately, because the daemon is watched live in a terminal during a
demo and buffered output would arrive after the event it describes. Components
take a `log` callable so tests can capture or silence it.
"""
from __future__ import annotations

from typing import Callable

LogFn = Callable[[str], None]


def log(message: str) -> None:
    """Print one log line and flush.

    Args:
        message: the full line, conventionally starting with a "[tag]".
    """
    print(message, flush=True)


def silent(message: str) -> None:
    """A LogFn that discards everything; the default in tests."""


class LogCapture:
    """A LogFn that records lines, for tests that assert on what was logged.

    Attributes:
        lines: every message received, in order.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, message: str) -> None:
        self.lines.append(message)

    def text(self) -> str:
        """All captured lines joined by newlines."""
        return "\n".join(self.lines)
