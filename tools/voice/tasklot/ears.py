"""Ears: the live daemon that turns board events into labels on the LCD.

    board --SPEAKER CAR n ordering--> Ears --start--> Recorder (ffmpeg)
    board --SPACE s <- CAR n parked--> Ears --stop---> Recorder -> Job queue
    worker: Transcriber -> TranscriptCleaner -> Condenser --"CAR n <label>"--> board
                                             -> Labeler (optional) --"CAR n <better>"--> board
    board --PLAYBACK CAR n reading back--> Ears --FULLCLR / FULL ... / FULLSHOW n--> board
    board --PICKUP CAR n collected--> Ears forgets the car

Threads, and why:
  * The main thread only reads the port and dispatches. It must keep draining,
    or the OS buffer overflows and lines arrive truncated (a garbled LCD).
  * A worker thread transcribes and labels, which takes seconds.
  * A capper closes any order still open after MAX_RECORDING_S (E-08).
  * An inbox watcher handles the say/command side-channel files.

Every collaborator is injected, and handle() and work_once() are synchronous,
so tests drive the whole daemon without threads, hardware, or subprocesses.
One re-entrant lock guards the Lot and the Recorder across those threads.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .cleaner import TranscriptCleaner
from .condenser import LCD_TEXT, Condenser, ascii_only, clip
from .config import MAX_RECORDING_S
from .labeler import Labeler
from .logs import LogFn, log as default_log
from .lot import Lot
from .protocol import (
    CLEAR, Collected, Left, Ordering, Parked, Playback, TaskEcho, car_command,
    full_text_commands, parse_line,
)
from .side_channels import FileInbox, Speaker
from .task import Task

CAP_CHECK_INTERVAL_S = 1.0     # how often the capper looks at the open order
INBOX_POLL_INTERVAL_S = 0.4    # how often the side-channel files are checked
RESET_COMMAND = "RESET"        # command-file word that wipes laptop and board
TASK_SOURCE = "mic"


@dataclass(frozen=True)
class Job:
    """One recording waiting to be transcribed.

    Attributes:
        car: the car it belongs to.
        order_id: the Lot order id it was recorded under; results are dropped
            if this is no longer current when they are ready.
        path: the WAV file.
    """

    car: int
    order_id: int
    path: Path


class Ears:
    """Wires the serial link, recorder, transcription, and labelling together.

    Args:
        send: callable(command) -> bool that writes one line to the board
            (SerialLink.send in the daemon; a recorder in tests).
        recorder: Recorder or NullRecorder.
        transcriber: Transcriber or FakeTranscriber.
        lot: shared state; a fresh Lot by default.
        cleaner, condenser, labeler: pipeline stages; the labeler defaults to
            disabled so nothing calls an LLM unless the caller asks.
        speaker: optional Speaker for the say inbox.
        say_inbox, cmd_inbox: optional FileInbox side channels.
        max_recording: seconds before an unparked order is closed.
        delete_recordings: remove each WAV once it has been transcribed.
        log: logging callable.
    """

    def __init__(self, send: Callable[[str], bool], recorder, transcriber, *,
                 lot: Optional[Lot] = None,
                 cleaner: Optional[TranscriptCleaner] = None,
                 condenser: Optional[Condenser] = None,
                 labeler: Optional[Labeler] = None,
                 speaker: Optional[Speaker] = None,
                 say_inbox: Optional[FileInbox] = None,
                 cmd_inbox: Optional[FileInbox] = None,
                 max_recording: float = MAX_RECORDING_S,
                 delete_recordings: bool = True,
                 log: LogFn = default_log):
        self.send = send
        self.recorder = recorder
        self.transcriber = transcriber
        self.lot = lot or Lot()
        self.cleaner = cleaner or TranscriptCleaner()
        self.condenser = condenser or Condenser()
        self.labeler = labeler or Labeler(enabled=False, log=log)
        self.speaker = speaker
        self.say_inbox = say_inbox
        self.cmd_inbox = cmd_inbox
        self.max_recording = max_recording
        self.delete_recordings = delete_recordings
        self.log = log
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self.stop_event = threading.Event()
        self._lock = threading.RLock()

    # -- board events (main thread) ----------------------------------------------
    def handle_line(self, line: str) -> None:
        """Log and dispatch one line from the board. Never raises (E-32)."""
        if not line:
            return
        self.log(f"[board] {line}")
        try:
            self.handle(parse_line(line))
        except Exception as exc:  # the read loop must never die on one bad line
            self.log(f"[handle] !! {type(exc).__name__}: {exc} -- on line {line!r}")

    def handle(self, event) -> None:
        """Apply one parsed board event. Unknown events are ignored.

        Raises:
            Whatever a collaborator raises; handle_line() catches it.
        """
        with self._lock:
            if isinstance(event, Ordering):
                self._on_ordering(event.car)
            elif isinstance(event, Parked):
                self._on_parked(event.space, event.car)
            elif isinstance(event, Left):
                self.lot.leave(event.space, event.car)
            elif isinstance(event, Playback):
                self._on_playback(event.car)
            elif isinstance(event, Collected):
                self._on_collected(event.car)
            elif isinstance(event, TaskEcho):
                self._on_task_echo(event.car, event.label)

    def _on_ordering(self, car: int) -> None:
        """A blank car passed the speaker: start recording its order."""
        if self.lot.recording == car and self.recorder.is_running():
            # A car lingering on the speaker is read again (E-09). Restarting
            # would throw away everything said so far.
            self.log(f"[mic] CAR {car} re-read at the speaker -- keeping the recording")
            return
        if self.lot.recording is not None and self.lot.recording != car:
            # The firmware replaced the order with this car (E-10). The first
            # car's speech is discarded; say so instead of dropping it silently.
            self.log(f"[mic] CAR {self.lot.recording}'s order abandoned -- CAR {car} took the speaker")
            self.recorder.discard()
        order_id = self.lot.begin_order(car)
        self.recorder.start(car, order_id)

    def _on_parked(self, space: int, car: int) -> None:
        """A car arrived on a space: close any open order, then record the move."""
        # Any park closes the order on the board, so it closes here too, and
        # the recording belongs to the car that ordered, not the one that parked
        # (E-11). Closed first, so a bad space number cannot leave the mic open.
        if self.lot.recording is not None:
            self._finish_order()
        self.lot.park(space, car)

    def _on_task_echo(self, car: int, label: str) -> None:
        """The board echoed the label it stored for `car`."""
        # The board echoes what it stored; learning it lets a restarted daemon
        # still read a car back (E-38). An empty echo (after DONE, or CAR n with
        # no text) means the car is blank on the board, so its task is done.
        self.lot.set_label(car, label)
        if not label:
            self.lot.tasks.pop(car, None)

    def _finish_order(self) -> None:
        """Close the open order and queue its recording for the worker."""
        closed = self.lot.close_order()
        if closed is None:
            return
        car, order_id = closed
        path = self.recorder.stop()
        if path is None:
            self.log(f"[mic] CAR {car}: nothing was recorded")
            return
        self.jobs.put(Job(car, order_id, path))

    def _on_playback(self, car: int) -> None:
        """A labelled car passed the speaker: send its full text for the read-back."""
        # The whole task goes on the glass, paged by the board. Nothing is spoken.
        full = self.lot.full_text(car)
        if not full:
            self.log(f"[show] CAR {car}: no text on the laptop -- nothing to show")
            return
        for command in full_text_commands(car, full):
            self.send(command)
        self.log(f"[show] CAR {car}: {full!r} on the glass")

    def _on_collected(self, car: int) -> None:
        """A car went through the pickup lane: its task is done."""
        if self.lot.recording == car:
            # Carried straight from the speaker to the pickup lane: the order
            # is cancelled, not transcribed for a car that is now blank (E-12).
            self.log(f"[mic] CAR {car} collected while ordering -- recording discarded")
            self.recorder.discard()
        self.lot.collect(car)

    # -- worker -------------------------------------------------------------------
    def work_once(self, job: Job) -> None:
        """Transcribe one recording and send its label(s).

        Sends the rule-based label at once, then an LLM upgrade if one passes the
        guards. Before each send, checks the order is still current, so a car
        collected or re-ordered meanwhile is not re-labelled (E-12, E-13).
        Never raises; errors are logged.
        """
        try:
            self._work(job)
        except Exception as exc:
            self.log(f"[worker] !! {type(exc).__name__}: {exc}")
        finally:
            if self.delete_recordings:
                _remove(job.path)

    def _work(self, job: Job) -> None:
        """The body of work_once(); may raise, and work_once() logs it."""
        car = job.car
        self.log("[whisper] transcribing...")
        text = self.transcriber.transcribe(job.path)
        if not text:
            self.log(f"[task] CAR {car}: nothing transcribed")
            return
        text = self.cleaner.clean(text)
        self.log(f"[clean] -> {text!r}")
        if self.cleaner.is_empty(text):
            # Sending an empty label would blank the car's row (E-02).
            self.log(f"[task] CAR {car}: nothing left after cleanup -- not sending")
            return
        condensed = self.condenser.condense(text)
        quick = clip(ascii_only(condensed.lcd or text), LCD_TEXT)
        task = Task.from_condensed(car, condensed, source=TASK_SOURCE)
        if not task.full:
            task.full = text

        # Two stages on purpose: the rule-based label lands about 0.6 s after
        # parking, so the LCD shows a real task instead of "CAR 3" while the
        # LLM thinks; the upgrade replaces it if it is better.
        with self._lock:
            if not self._still_current(job, "label"):
                return
            self.lot.set_task(task)
            self.lot.set_label(car, quick)
            self.log(f"[task] CAR {car}: {task.full!r} -> LCD {quick!r} (quick)")
            self.send(car_command(car, quick))

        better = self.labeler.label(text)
        if not better:
            self.log(f"[llm] CAR {car}: no upgrade, keeping {quick!r}")
            return
        if better == quick:
            return
        with self._lock:
            if not self._still_current(job, "upgrade"):
                return
            self.lot.set_label(car, better)
            self.log(f"[llm] CAR {car}: {quick!r} -> {better!r} (upgrade)")
            self.send(car_command(car, better))

    def _still_current(self, job: Job, what: str) -> bool:
        """True if the job's order is still current; otherwise logs that `what` was dropped."""
        if self.lot.is_current(job.car, job.order_id):
            return True
        self.log(f"[task] CAR {job.car}: dropped stale {what} (collected or re-ordered)")
        return False

    def drain_jobs(self) -> int:
        """Run every queued job on the calling thread (tests and shutdown).

        Returns:
            int: how many jobs ran.
        """
        count = 0
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return count
            self.work_once(job)
            self.jobs.task_done()
            count += 1

    # -- timers and side channels ---------------------------------------------------
    def check_cap(self) -> bool:
        """Close an order nobody parked once it passes max_recording (E-08, E-14).

        Returns:
            bool: True if an order was capped.
        """
        with self._lock:
            car = self.lot.recording
            if car is None or not self.recorder.is_running():
                return False
            if self.recorder.elapsed() <= self.max_recording:
                return False
            self.log(f"[mic] CAR {car} never parked -- capping at {int(self.max_recording)}s")
            self._finish_order()
            return True

    def handle_command(self, text: str) -> None:
        """Act on a line from the command inbox: RESET, or a raw board command.

        RESET forgets every task the laptop knows and clears the board, which is
        what you want between demo runs (including any phantom car a partial
        RFID read registered).
        """
        if text.strip().upper() == RESET_COMMAND:
            with self._lock:
                self.lot.clear()
            self.send(CLEAR)
            self.log("[reset] laptop memory wiped, board cleared")
        elif text.strip():
            self.send(text.strip())

    def poll_inboxes(self) -> None:
        """Check both side-channel files once; errors are logged."""
        for inbox, act, tag in ((self.say_inbox, self._say, "saypipe"),
                                (self.cmd_inbox, self.handle_command, "cmdpipe")):
            if inbox is None:
                continue
            try:
                text = inbox.poll()
                if text:
                    act(text)
            except Exception as exc:
                self.log(f"[{tag}] !! {exc}")

    def _say(self, text: str) -> None:
        """Speak a line from the say inbox, if a Speaker is configured."""
        if self.speaker is not None:
            self.speaker.speak(text)

    def on_reconnect(self) -> None:
        """After the board resets it has forgotten every label (E-37): re-send
        the ones the laptop knows. Occupancy is cleared; the board reports
        parked cars again as it re-detects them. Car numbers are assigned in the
        order tags are first seen, so after a reset a physical car may get a
        different number; firmware persistence (REMEMBER 1) is the real fix."""
        with self._lock:
            self.lot.spaces = [None] * len(self.lot.spaces)
            labels = sorted(self.lot.labels.items())
        for car, label in labels:
            self.send(car_command(car, label))
        if labels:
            self.log(f"[serial] re-sent {len(labels)} label(s) after reconnect")

    # -- running -----------------------------------------------------------------
    def startup_report(self) -> None:
        """Log missing tools once, clearly, before the first order (E-06)."""
        problems = getattr(self.transcriber, "problems", lambda: [])()
        for problem in problems:
            self.log(f"[whisper] !! {problem}")
        if self.speaker is not None:
            voice = self.speaker.pick_voice()
            self.log(f"[voice] using {voice or 'system default (no premium voice installed)'}")

    def start_background_threads(self) -> None:
        """Start the worker, the capper, and the inbox watcher (daemon threads)."""
        for inbox in (self.say_inbox, self.cmd_inbox):
            if inbox is not None:
                inbox.reset()
        for target in (self._worker_loop, self._capper_loop, self._inbox_loop):
            threading.Thread(target=target, daemon=True).start()

    def run(self, readline: Callable[[], Optional[str]]) -> None:
        """Read and dispatch board lines until stop_event is set.

        Args:
            readline: SerialLink.readline; returns a line, "" on timeout, or None.
        """
        while not self.stop_event.is_set():
            line = readline()
            if line:
                self.handle_line(line)

    def shutdown(self) -> None:
        """Stop the threads and close any open recording."""
        self.stop_event.set()
        with self._lock:
            self.recorder.stop()

    def _worker_loop(self) -> None:
        """Worker thread: run queued transcription jobs until stopped."""
        while not self.stop_event.is_set():
            try:
                job = self.jobs.get(timeout=CAP_CHECK_INTERVAL_S)
            except queue.Empty:
                continue
            self.work_once(job)
            self.jobs.task_done()

    def _capper_loop(self) -> None:
        """Capper thread: close an order nobody parked, once a second."""
        while not self.stop_event.wait(CAP_CHECK_INTERVAL_S):
            try:
                self.check_cap()
            except Exception as exc:
                self.log(f"[capper] !! {exc}")

    def _inbox_loop(self) -> None:
        """Inbox thread: poll the side-channel files until stopped."""
        while not self.stop_event.wait(INBOX_POLL_INTERVAL_S):
            self.poll_inboxes()


def _remove(path: Path) -> None:
    """Delete a scratch recording; a missing file is fine."""
    try:
        Path(path).unlink()
    except OSError:
        pass
