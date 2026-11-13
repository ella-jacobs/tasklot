"""Recorder: microphone capture with ffmpeg, one WAV per order.

ffmpeg records the default macOS input (avfoundation) to a 16 kHz mono WAV, the
format whisper.cpp wants. Each order gets its own file name, and any leftover
file with that name is deleted before recording starts, so a failed start can
never hand a previous order's audio to this one (DESIGN.md E-05).

Stopping is the delicate part. ffmpeg only writes a valid WAV header when it
exits cleanly; a SIGKILL leaves placeholder sizes that whisper reads as garbage.
So stop() asks politely ("q" on stdin), then sends SIGINT (ffmpeg flushes on
INT), and only then kills (E-04). It also never stops inside ffmpeg's device
start-up window, which can leave no file at all (E-03).

NullRecorder stands in when transcription is faked (TASKLOT_FAKE_TRANSCRIPT):
it tracks the same state without starting a process.
"""
from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .config import MIN_HOLD_S
from .logs import LogFn, log as default_log

SAMPLE_RATE_HZ = 16000      # whisper.cpp expects 16 kHz mono
STOP_GRACE_S = 3.0          # how long each polite stop step may take
KILL_WAIT_S = 2.0

ProcessFactory = Callable[..., "subprocess.Popen"]


def wav_name(car: int, order_id: int) -> str:
    """File name for one order's recording, unique per car and order."""
    return f"tasklot_order_car{car}_{order_id}.wav"


class Recorder:
    """Starts and stops one ffmpeg recording at a time.

    Args:
        rec_dir: directory for WAV files.
        mic: ffmpeg avfoundation input spec (":0" is the default microphone).
        process_factory: Popen-like callable, injectable for tests.
        clock, sleep: time sources, injectable for tests.
        min_hold: minimum seconds between start and stop.
        log: logging callable.
    """

    def __init__(self, rec_dir: Path, mic: str = ":0", *,
                 process_factory: ProcessFactory = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 min_hold: float = MIN_HOLD_S, log: LogFn = default_log):
        self.rec_dir = Path(rec_dir)
        self.mic = mic
        self.process_factory = process_factory
        self.clock = clock
        self.sleep = sleep
        self.min_hold = min_hold
        self.log = log
        self._proc = None
        self._path: Optional[Path] = None
        self._started = 0.0

    def command(self, path: Path) -> list[str]:
        """The ffmpeg command line that records to `path`."""
        return ["ffmpeg", "-y", "-f", "avfoundation", "-i", self.mic,
                "-ar", str(SAMPLE_RATE_HZ), "-ac", "1", str(path)]

    def start(self, car: int, order_id: int) -> Optional[Path]:
        """Start recording an order. Stops (and keeps) any recording in progress.

        Args:
            car: car number, for the file name and the log.
            order_id: the Lot's order id, for the file name.

        Returns:
            Path | None: where the WAV will be written, or None if ffmpeg could
            not be started (logged).
        """
        if self.is_running():
            self.stop()
        path = self.rec_dir / wav_name(car, order_id)
        _remove(path)
        try:
            self._proc = self.process_factory(self.command(path), stdin=subprocess.PIPE,
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as exc:
            self._proc, self._path = None, None
            self.log(f"[mic] !! FAILED to start ffmpeg: {exc}")
            return None
        self._path = path
        self._started = self.clock()
        self.log(f"[mic] recording for CAR {car} -- park it to finish")
        return path

    def is_running(self) -> bool:
        """True while the ffmpeg process is alive."""
        return self._proc is not None and self._proc.poll() is None

    def elapsed(self) -> float:
        """Seconds since the current recording started (0 if none)."""
        return self.clock() - self._started if self.is_running() else 0.0

    def stop(self) -> Optional[Path]:
        """Stop the recording so ffmpeg writes a valid WAV.

        Returns:
            Path | None: the recording's path if a file exists, else None
            (nothing was started, or ffmpeg died without writing).
        """
        proc, path = self._proc, self._path
        self._proc, self._path = None, None
        if proc is None:
            return None
        if proc.poll() is None:
            held = self.clock() - self._started
            if held < self.min_hold:
                self.sleep(self.min_hold - held)   # never stop inside ffmpeg's init window
            self._stop_process(proc)
        return path if path is not None and path.exists() else None

    def discard(self) -> None:
        """Stop and delete the current recording (an abandoned order)."""
        _remove(self.stop())

    def _stop_process(self, proc) -> None:
        """Escalate: "q" on stdin, then SIGINT, then SIGKILL."""
        try:
            proc.communicate(input=b"q", timeout=STOP_GRACE_S)
            return
        except Exception:  # TimeoutExpired, or a broken stdin pipe
            pass
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=STOP_GRACE_S)
            return
        except Exception:
            pass
        try:
            proc.kill()
            proc.wait(timeout=KILL_WAIT_S)
        except Exception:  # already gone; nothing more can be done
            pass
        self.log("[mic] !! had to SIGKILL ffmpeg -- WAV may be truncated")


class NullRecorder:
    """A Recorder with no process, for faked transcription and tests.

    start() returns a path that is never written; stop() returns it so the
    pipeline proceeds and the FakeTranscriber supplies the text.
    """

    def __init__(self, rec_dir: Path = Path("."), log: LogFn = default_log,
                 clock: Callable[[], float] = time.monotonic):
        self.rec_dir = Path(rec_dir)
        self.log = log
        self.clock = clock
        self._path: Optional[Path] = None
        self._started = 0.0

    def start(self, car: int, order_id: int) -> Optional[Path]:
        """Pretend to record; returns the path a real recording would use."""
        self._path = self.rec_dir / wav_name(car, order_id)
        self._started = self.clock()
        self.log(f"[mic] (mock) recording for CAR {car}")
        return self._path

    def is_running(self) -> bool:
        """True between start() and stop()."""
        return self._path is not None

    def elapsed(self) -> float:
        """Seconds since start() (0 if not recording)."""
        return self.clock() - self._started if self._path is not None else 0.0

    def stop(self) -> Optional[Path]:
        """End the pretend recording and return its path (or None)."""
        path, self._path = self._path, None
        return path

    def discard(self) -> None:
        """End the pretend recording."""
        self._path = None


def _remove(path: Optional[Path]) -> None:
    """Delete a file if it exists; ignore errors (it is scratch audio)."""
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
