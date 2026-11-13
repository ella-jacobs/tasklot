"""SerialLink: the one connection to the board, paced and self-healing.

Every write goes through send(), which holds a lock (the read loop, the worker
thread, and the command-file watcher all send) and waits until at least
`pacing` seconds have passed since the previous write, because the Mega's
64-byte RX buffer overflows on bursts and two commands merge on the LCD (E-31).

Reads go through readline(). If the port disappears (USB unplugged), the link
closes the dead handle, logs once, and reopens with backoff instead of spinning
on it forever (E-36). After a successful reopen it calls `on_reconnect`, which
Ears uses to re-send labels to a board that just reset (E-37).

pyserial is imported lazily by the default factory, so tests and the offline
CLI without --push never need it.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from .config import BAUD, RESET_DELAY_S, SEND_PACING_S
from .logs import LogFn, log as default_log
from .protocol import BOARD_LINE_MAX, encode

READ_TIMEOUT_S = 1.0                     # readline() returns "" after this long
RECONNECT_BACKOFF_S = (1.0, 2.0, 4.0, 8.0)  # then stays at the last value

SerialFactory = Callable[[str, int, float], Any]


class SerialLinkError(Exception):
    """The port could not be opened. The message says what to check."""


def pyserial_factory(port: str, baud: int, timeout: float):
    """Open a real port with pyserial.

    Raises:
        SerialLinkError: pyserial is missing.
        serial.SerialException / OSError: the port cannot be opened.
    """
    try:
        import serial  # noqa: PLC0415 (optional dependency, imported on demand)
    except ImportError:
        raise SerialLinkError("pyserial is not installed for this Python "
                              "(tools/voice/README.md shows the venv setup)") from None
    return serial.Serial(port, baud, timeout=timeout)


class SerialLink:
    """A paced, reconnecting line-oriented serial connection.

    Args:
        port: device path, e.g. /dev/cu.usbmodem101.
        baud: line speed.
        serial_factory: callable(port, baud, timeout) -> handle with readline(),
            write(), flush(), close(). Defaults to pyserial.
        pacing: minimum seconds between two writes.
        reset_delay: seconds to wait after opening, while the Mega reboots.
        clock, sleep: time sources, injectable for tests.
        log: logging callable.
        on_reconnect: called with no arguments after a reopen succeeds.
    """

    def __init__(self, port: str, baud: int = BAUD, *,
                 serial_factory: SerialFactory = pyserial_factory,
                 pacing: float = SEND_PACING_S, reset_delay: float = RESET_DELAY_S,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 log: LogFn = default_log,
                 on_reconnect: Optional[Callable[[], None]] = None):
        self.port = port
        self.baud = baud
        self.serial_factory = serial_factory
        self.pacing = pacing
        self.reset_delay = reset_delay
        self.clock = clock
        self.sleep = sleep
        self.log = log
        self.on_reconnect = on_reconnect
        self._handle = None
        self._write_lock = threading.Lock()
        self._last_write: Optional[float] = None

    @property
    def connected(self) -> bool:
        """True while a handle is open."""
        return self._handle is not None

    def open(self) -> None:
        """Open the port and wait out the board's reset.

        Raises:
            SerialLinkError: the port cannot be opened; the message names
                TASKLOT_PORT and notes that only one program can hold it (E-35, E-39).
        """
        try:
            self._handle = self.serial_factory(self.port, self.baud, READ_TIMEOUT_S)
        except SerialLinkError:
            raise
        except Exception as exc:  # pyserial raises SerialException (an OSError) or ValueError
            raise SerialLinkError(
                f"cannot open serial port {self.port!r} ({exc}).\n"
                "Check the board is plugged in and set TASKLOT_PORT (ls /dev/cu.usbmodem*).\n"
                "Only one program can hold the port: close the Arduino Serial Monitor "
                "and the simulator page.") from exc
        # Opening toggles DTR and resets the Mega; writes during boot are lost.
        self.sleep(self.reset_delay)

    def close(self) -> None:
        """Close the port if open. Safe to call twice."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except Exception:  # closing a dead port can raise; it is gone either way
                pass

    def discard_input(self) -> None:
        """Drop anything already received (e.g. the boot banner)."""
        if self._handle is not None and hasattr(self._handle, "reset_input_buffer"):
            self._handle.reset_input_buffer()

    def send(self, command: str) -> bool:
        """Write one command line, paced and ASCII-only.

        Args:
            command: the command without a line ending.

        Returns:
            bool: True if written; False if the port is closed or the write
            failed (logged, never raised, so a dead port cannot crash a worker).
        """
        if len(command) > BOARD_LINE_MAX:
            self.log(f"[->board] warning: {len(command)} chars; the board keeps {BOARD_LINE_MAX}")
        with self._write_lock:
            if self._last_write is not None:
                wait = self._last_write + self.pacing - self.clock()
                if wait > 0:
                    self.sleep(wait)
            handle = self._handle
            if handle is None:
                self.log(f"[->board] !! not connected, dropped: {command}")
                return False
            try:
                handle.write(encode(command))
                handle.flush()
            except Exception as exc:
                self.log(f"[->board] !! write failed: {exc}")
                return False
            finally:
                self._last_write = self.clock()
            self.log(f"[->board] {command}")
            return True

    def readline(self) -> Optional[str]:
        """Read one line from the board.

        Returns:
            str | None: the stripped line ("" on read timeout), or None if the
            port dropped; in that case the link has already reconnected (or is
            still retrying inside this call) and the caller just reads again.
        """
        if self._handle is None:
            self._reconnect()
            return None
        try:
            raw = self._handle.readline()
        except Exception as exc:
            self.log(f"[serial] !! lost the board ({type(exc).__name__}: {exc}) -- reconnecting")
            self.close()
            self._reconnect()
            return None
        return raw.decode(errors="replace").strip()

    def read_for(self, seconds: float) -> list[str]:
        """Collect non-empty lines for about `seconds` (used after --push)."""
        deadline = self.clock() + seconds
        lines = []
        while self.clock() < deadline:
            line = self.readline()
            if line:
                lines.append(line)
            elif line is None:
                break
        return lines

    def _reconnect(self) -> None:
        """Reopen with backoff until it works, then call on_reconnect."""
        attempt = 0
        while self._handle is None:
            delay = RECONNECT_BACKOFF_S[min(attempt, len(RECONNECT_BACKOFF_S) - 1)]
            self.sleep(delay)
            try:
                self.open()
            except SerialLinkError:
                attempt += 1
                continue
        self.log(f"[serial] reconnected to {self.port}")
        if self.on_reconnect is not None:
            self.on_reconnect()
