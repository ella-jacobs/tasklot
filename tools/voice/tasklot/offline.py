"""OfflineTool: voice memo or typed text -> tasks.json -> (optionally) the board.

The offline path, for when there is no live order: a memo recorded on a phone,
the newest Apple Voice Memo, a folder that recordings are dropped into, or typed
text to load a demo quickly. It reuses the Condenser, Lot/Task (tasks.json), and
SerialLink, so --push gets the same pacing as the daemon (DESIGN.md E-31).

Output (the preview box, the per-task summary, the messages) matches what the
original tasklot_voice.py printed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO

from .condenser import LCD_TEXT, Condenser
from .config import BAUD, MAX_CARS, Settings
from .logs import silent
from .lot import Lot, LotFull
from .protocol import LOT, car_command
from .serial_link import SerialLink
from .task import Task

VOICE_MEMO_DIR = Path("~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings").expanduser()
AUDIO_EXTENSIONS = (".m4a", ".wav", ".mp3", ".aiff", ".aif", ".caf", ".qta", ".mp4")
PREVIEW_ORDER = [1, 2, 3, 4]     # without a board, cars 1-4 stand in spaces 1-4
WATCH_POLL_S = 1.5               # how often --watch looks for new files
COPY_SETTLE_S = 0.6              # wait between size checks while a file is still copying
PUSH_REPLY_WAIT_S = 0.4          # how long to collect the board's reply to LOT


class OfflineError(Exception):
    """A user-facing failure; the CLI prints the message and exits non-zero."""


class OfflineTool:
    """Adds tasks to tasks.json, previews the LCD, and pushes labels to the board.

    Args:
        settings: paths and serial settings.
        transcriber: object with transcribe(path) -> str (ScriptTranscriber).
        condenser: the Condenser to use.
        out, err: streams for normal output and progress/warnings.
        link_factory: callable(port) -> SerialLink, injectable for tests.
        sleep: time source for --watch, injectable for tests.
    """

    def __init__(self, settings: Settings, transcriber, *, condenser: Optional[Condenser] = None,
                 out: TextIO = sys.stdout, err: TextIO = sys.stderr,
                 link_factory: Optional[Callable[[str], SerialLink]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.transcriber = transcriber
        self.condenser = condenser or Condenser()
        self.out = out
        self.err = err
        self.link_factory = link_factory or self._default_link
        self.sleep = sleep
        self.lot, ok = Lot.load(settings.tasks_file, max_cars=MAX_CARS)
        if not ok:
            print("  tasks.json unreadable, starting fresh", file=self.err)

    # -- tasks ---------------------------------------------------------------------
    def add(self, text: str, car: Optional[int] = None, source: str = "") -> Optional[Task]:
        """Condense `text` into a task for `car` (or the next free car), print
        a summary, and save tasks.json.

        Returns:
            Task | None: the new task, or None if nothing usable was said.

        Raises:
            OfflineError: no car given and every car already has a task.
        """
        condensed = self.condenser.condense(text)
        if not condensed.full:
            print("  nothing usable in that recording - skipped", file=self.err)
            return None
        if car is None:
            try:
                car = self.lot.next_free_car()
            except LotFull:
                raise OfflineError(f"All {MAX_CARS} cars have tasks. Pass --car N to overwrite one.") from None
        task = Task.from_condensed(car, condensed, source=source)
        self.lot.set_task(task)
        print(f"\n  CAR {car}", file=self.out)
        print(f"  full : {task.full}", file=self.out)
        print("  lcd  : %-18s  (%d/%d)" % (task.lcd, len(task.lcd), LCD_TEXT), file=self.out)
        if task.due:
            print(f"  due  : {task.due}", file=self.out)
        self.save()
        return task

    def add_audio(self, path: Path, car: Optional[int] = None) -> Optional[Task]:
        """Transcribe an audio file and add it as a task (see add())."""
        return self.add(self.transcriber.transcribe(path), car, Path(path).name)

    def clear(self) -> Path:
        """Empty tasks.json. Returns where it was written."""
        self.lot = Lot(max_cars=MAX_CARS)
        return self.save()

    def save(self) -> Path:
        """Write tasks.json."""
        return self.lot.save(self.settings.tasks_file)

    @property
    def has_tasks(self) -> bool:
        """True if any car has a task."""
        return bool(self.lot.tasks)

    # -- the LCD, on paper ------------------------------------------------------------
    def preview(self, order: Iterable[int] = PREVIEW_ORDER) -> None:
        """Print what the LCD would show, with cars `order` in spaces 1-4."""
        print("\n   +--------------------+", file=self.out)
        for line in Condenser.lot_lines(self.lot.rows(order=list(order))):
            print(f"   |{line}|", file=self.out)
        print("   +--------------------+\n", file=self.out)

    # -- sources ----------------------------------------------------------------------
    @staticmethod
    def latest_memo(folder: Path = VOICE_MEMO_DIR) -> Path:
        """The newest Apple Voice Memo. Reading the folder needs Full Disk Access
        for the terminal, which is the usual reason it comes back unreadable.

        Raises:
            OfflineError: the folder is unreadable or holds no recordings.
        """
        if not folder.is_dir():
            raise OfflineError("Voice Memos folder not readable. Grant Full Disk Access, or pass a file.")
        files = [p for p in folder.iterdir() if p.name.lower().endswith(AUDIO_EXTENSIONS)]
        if not files:
            raise OfflineError(f"No recordings found in {folder}")
        return max(files, key=lambda p: p.stat().st_mtime)

    def watch(self, folder: Path, push_port: Optional[str] = None,
              max_polls: Optional[int] = None) -> None:
        """Turn each new recording dropped into `folder` into the next task.

        Files already there are ignored. A file is read only once its size
        stops changing, so a copy in progress is not transcribed half-written.

        Args:
            folder: directory to watch (created if missing).
            push_port: push to the board after each new task, if given.
            max_polls: stop after this many polls (tests); None runs until Ctrl-C.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        seen = self._audio_files(folder)
        print(f"  watching {folder} - drop a recording in. ctrl-c to stop.", file=self.out)
        print(f"  ({len(seen)} file(s) already there, ignoring those)", file=self.out)
        polls = 0
        try:
            while max_polls is None or polls < max_polls:
                polls += 1
                self.sleep(WATCH_POLL_S)
                now = self._audio_files(folder)
                for name in sorted(now - seen):
                    path = folder / name
                    self._wait_for_copy(path)
                    self.add_audio(path)
                    self.preview()
                    if push_port:
                        self.push(push_port)
                seen = now
        except KeyboardInterrupt:
            print(f"\n  stopped. {self.settings.tasks_file}", file=self.out)

    @staticmethod
    def _audio_files(folder: Path) -> set[str]:
        """Names of the audio files directly in `folder`."""
        return {p.name for p in folder.iterdir() if p.name.lower().endswith(AUDIO_EXTENSIONS)}

    def _wait_for_copy(self, path: Path) -> None:
        """Return once the file's size stops changing (a copy has finished)."""
        size = -1
        while size != path.stat().st_size:
            size = path.stat().st_size
            self.sleep(COPY_SETTLE_S)

    # -- the board ----------------------------------------------------------------------
    def push(self, port: str) -> list[str]:
        """Send every task's label to the board, then LOT, and print the reply.

        Only one program can hold the port, so close the simulator and the
        daemon first.

        Returns:
            list[str]: the lines the board replied with.

        Raises:
            SerialLinkError: the port cannot be opened.
        """
        print(f"  opening {port} at {BAUD} ...", file=self.err)
        link = self.link_factory(port)
        link.open()
        try:
            # The Mega just reset; its boot banner is not a reply to us.
            link.discard_input()
            for car in sorted(self.lot.tasks):
                command = car_command(car, self.lot.tasks[car].lcd)
                link.send(command)
                print(f"  -> {command}", file=self.err)
            link.send(LOT)
            reply = link.read_for(PUSH_REPLY_WAIT_S)
        finally:
            link.close()
        if reply:
            print("\n" + "\n".join(reply), file=self.out)
        return reply

    def _default_link(self, port: str) -> SerialLink:
        """A paced SerialLink for --push that logs nothing: push() prints its own
        progress to stderr, matching the original tool's output."""
        return SerialLink(port, self.settings.baud, pacing=self.settings.pacing,
                          reset_delay=self.settings.reset_delay, log=silent)

