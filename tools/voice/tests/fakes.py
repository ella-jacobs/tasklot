"""Test doubles shared by the unit tests: a fake clock, a fake serial port, a
fake ffmpeg process, and a recording sender. None of them touch hardware,
subprocesses, or real time.
"""
from __future__ import annotations

import subprocess


class FakeClock:
    """A manual clock. sleep() advances it instead of blocking.

    Attributes:
        now: current time in seconds.
        sleeps: every duration passed to sleep(), in order.
    """

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePort:
    """Stands in for a pyserial Serial object.

    Args:
        lines: byte strings readline() returns in order; b"" once exhausted.
        clock: optional FakeClock, to timestamp writes.
        fail_reads_after: raise OSError on read number N (0-based), then stop.
        fail_writes: raise OSError on every write.
    """

    def __init__(self, lines=(), clock=None, fail_reads_after=None, fail_writes=False):
        self.lines = list(lines)
        self.clock = clock
        self.fail_reads_after = fail_reads_after
        self.fail_writes = fail_writes
        self.reads = 0
        self.writes: list[bytes] = []
        self.write_times: list[float] = []
        self.closed = False
        self.input_reset = False

    def readline(self) -> bytes:
        if self.fail_reads_after is not None and self.reads >= self.fail_reads_after:
            raise OSError("device disconnected")
        self.reads += 1
        return self.lines.pop(0) if self.lines else b""

    def write(self, data: bytes) -> int:
        if self.fail_writes:
            raise OSError("write failed")
        self.writes.append(data)
        if self.clock is not None:
            self.write_times.append(self.clock())
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def reset_input_buffer(self) -> None:
        self.input_reset = True

    def wire(self) -> str:
        """Everything written, decoded."""
        return b"".join(self.writes).decode("ascii")


class PortFactory:
    """A serial_factory that hands out prepared FakePorts, or raises.

    Args:
        outcomes: each a FakePort to return or an Exception to raise, in order.
    """

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, port, baud, timeout):
        self.calls.append((port, baud, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeProcess:
    """Stands in for the ffmpeg Popen object.

    Args:
        on_q: what communicate(b"q") does: "exit" or "hang".
        on_sigint: what wait() after SIGINT does: "exit" or "hang".
        exited: True to behave as if ffmpeg already died.
        writes_file: a Path to create when the process stops (a "WAV").
    """

    def __init__(self, on_q="exit", on_sigint="exit", exited=False, writes_file=None):
        self.on_q = on_q
        self.on_sigint = on_sigint
        self.returncode = 1 if exited else None
        self.writes_file = writes_file
        self.events: list[str] = []
        self._sigint = False

    def poll(self):
        return self.returncode

    def _finish(self):
        self.returncode = 0
        if self.writes_file is not None:
            self.writes_file.write_bytes(b"RIFF" + b"\0" * 9000)

    def communicate(self, input=None, timeout=None):
        self.events.append(f"communicate {input!r}")
        if self.on_q == "hang":
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        self._finish()
        return (b"", b"")

    def send_signal(self, sig):
        self.events.append(f"signal {int(sig)}")
        self._sigint = True

    def wait(self, timeout=None):
        self.events.append("wait")
        if self._sigint and self.on_sigint == "hang" and self.returncode is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        if self.returncode is None:
            self._finish()
        return self.returncode

    def kill(self):
        self.events.append("kill")
        self.returncode = -9


class RecordingSender:
    """Stands in for SerialLink.send: records every command."""

    def __init__(self):
        self.sent: list[str] = []

    def __call__(self, command: str) -> bool:
        self.sent.append(command)
        return True
