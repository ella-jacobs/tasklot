"""The serial protocol between the board and the laptop (DESIGN.md section 3).

Board -> laptop: parse_line() turns one line into a BoardEvent. Patterns are
anchored at the start of the line, so a label that happens to contain event-like
text (the echo "TASK 3 CAR 9 reading back") cannot trigger an event (E-33).
Columns are padded with runs of spaces by the firmware, so patterns use \\s+.

Laptop -> board: the command formatters below produce the exact strings the
firmware matches. Any change here breaks the board and the simulator, which is
why tests pin them byte for byte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

# The firmware's command buffer is 48 bytes, so a line over 47 characters is
# truncated on the board. FULL chunks stay well under it.
BOARD_LINE_MAX = 47
# Read-back text goes up in chunks of at most this many characters; "FULL " plus
# 40 is 45, inside BOARD_LINE_MAX, and short enough not to overrun the RX buffer.
FULL_CHUNK_MAX = 40


# -- events ------------------------------------------------------------------
@dataclass(frozen=True)
class Ordering:
    """A blank car passed the speaker reader: start recording its order."""
    car: int


@dataclass(frozen=True)
class Playback:
    """A car with a label passed the speaker: show its full text."""
    car: int


@dataclass(frozen=True)
class Parked:
    """A car arrived on a space."""
    space: int
    car: int


@dataclass(frozen=True)
class Left:
    """A car left a space."""
    space: int
    car: int


@dataclass(frozen=True)
class Collected:
    """A car went through the pickup lane: its task is done."""
    car: int


@dataclass(frozen=True)
class TaskEcho:
    """The board stored a label for a car ("" after DONE or a pickup)."""
    car: int
    label: str


@dataclass(frozen=True)
class NewCar:
    """A new tag was registered as car `car`."""
    car: int
    uid: str


@dataclass(frozen=True)
class Pong:
    """Reply to PING."""


@dataclass(frozen=True)
class Unknown:
    """Anything else: lot printouts, the boot banner, garbled lines."""
    line: str


BoardEvent = Union[Ordering, Playback, Parked, Left, Collected, TaskEcho, NewCar, Pong, Unknown]

_PATTERNS = [
    (re.compile(r"^SPEAKER\s+CAR\s+(\d+)\s+ordering\b"), lambda m: Ordering(int(m[1]))),
    (re.compile(r"^PLAYBACK\s+CAR\s+(\d+)\s+reading back\b"), lambda m: Playback(int(m[1]))),
    (re.compile(r"^SPACE\s+(\d+)\s*<-\s*CAR\s+(\d+)\s+parked\b"), lambda m: Parked(int(m[1]), int(m[2]))),
    (re.compile(r"^SPACE\s+(\d+)\s*->\s*CAR\s+(\d+)\s+left\b"), lambda m: Left(int(m[1]), int(m[2]))),
    (re.compile(r"^PICKUP\s+CAR\s+(\d+)\s+collected\b"), lambda m: Collected(int(m[1]))),
    # After DONE or a pickup the echo is "TASK n " with nothing after the space.
    (re.compile(r"^TASK\s+(\d+)(?:\s(.*))?$"), lambda m: TaskEcho(int(m[1]), (m[2] or "").strip())),
    (re.compile(r"^\* NEW CAR registered\s*->\s*CAR\s+(\d+)\s+UID\s+([0-9A-F ]+)"),
     lambda m: NewCar(int(m[1]), m[2].strip())),
    (re.compile(r"^PONG\b"), lambda m: Pong()),
]


def parse_line(line: str) -> BoardEvent:
    """Parse one line from the board.

    Args:
        line: one line, with or without its line ending.

    Returns:
        BoardEvent: the matching event, or Unknown for anything else
        (including empty and garbled lines). Never raises.
    """
    text = line.strip()
    for pattern, build in _PATTERNS:
        m = pattern.match(text)
        if m:
            return build(m)
    return Unknown(text)


# -- commands ----------------------------------------------------------------
def car_command(car: int, label: str) -> str:
    """Set a car's label: "CAR <n> <label>" (the board keeps 18 characters)."""
    return f"CAR {car} {label}"


def done_command(car: int) -> str:
    """Blank a car's label and close any order or read-back."""
    return f"DONE {car}"


CLEAR = "CLEAR"      # blank every label
LOT = "LOT"          # end any read-back and reprint the lot
PING = "PING"        # link check; the board replies PONG
FULLCLR = "FULLCLR"  # empty the read-back buffer


def chunk_text(text: str, size: int = FULL_CHUNK_MAX) -> list[str]:
    """Split text into chunks of at most `size` characters on word boundaries.

    A single word longer than `size` is split into `size`-character pieces, so
    no chunk ever exceeds `size` (E-16). Empty text gives no chunks.

    Args:
        text: the full read-back text.
        size: maximum chunk length.

    Returns:
        list[str]: the chunks, in order.
    """
    words = []
    for word in text.split():
        words.extend(word[i:i + size] for i in range(0, len(word), size))
    chunks, line = [], ""
    for word in words:
        if line and len(line) + len(word) + 1 > size:
            chunks.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        chunks.append(line)
    return chunks


def full_text_commands(car: int, text: str) -> list[str]:
    """The command sequence that shows `text` as car `car`'s read-back.

    Returns:
        list[str]: FULLCLR, one "FULL <chunk>" per chunk, then "FULLSHOW <n>".
    """
    return [FULLCLR] + [f"FULL {chunk}" for chunk in chunk_text(text)] + [f"FULLSHOW {car}"]


def encode(command: str) -> bytes:
    """Wire bytes for one command: ASCII with non-ASCII dropped, plus "\\n".

    The board stores bytes as they arrive, so a multi-byte character would show
    as garbage glyphs; dropping it is the safe choice (E-17).
    """
    return (command + "\n").encode("ascii", "ignore")
