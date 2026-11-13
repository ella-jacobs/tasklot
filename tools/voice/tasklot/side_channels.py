"""Side channels into the running daemon: spoken lines and board commands.

Only one program can hold the serial port, so while the daemon runs, nothing
else can talk to the board. Two watched files fill that gap. By default they
live in the per-user temp directory (see config.py), which on macOS is $TMPDIR:

    echo "Drive up when you are ready" > "$TMPDIR/tasklot_say.txt"   # spoken aloud
    echo CLEAR > "$TMPDIR/tasklot_cmd.txt"                            # sent to the board
    echo RESET > "$TMPDIR/tasklot_cmd.txt"                            # wipe laptop + board

FileInbox watches one file by modification time; SayVoice wraps macOS `say`
with the best installed voice. (It is named for what it does: in the rest of
the project "the speaker" is the RFID reader in the ordering lane.) Paths come from Settings (E-43).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import DEFAULT_SAY_RATE
from .logs import LogFn, log as default_log

# `say` defaults to a robotic legacy voice; prefer a Premium/Enhanced one if
# installed (System Settings > Accessibility > Spoken Content > Manage Voices).
VOICE_PREFERENCES = ("Ava (Premium)", "Zoe (Premium)", "Evan (Premium)",
                     "Allison (Premium)", "Samantha (Enhanced)", "Ava (Enhanced)", "Samantha")
VOICE_LIST_TIMEOUT_S = 10
OWNER_ONLY = 0o600     # inbox files: read and write for the user only


class FileInbox:
    """Reports new content written to a file, by modification time.

    Args:
        path: the file to watch.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._last_mtime = 0.0

    def reset(self) -> None:
        """Blank the file and remember its mtime, so a restart does not replay
        whatever was written last time (E-43). A new file is created owner-only,
        and a symlink planted at the path is never followed, so reset cannot
        truncate some other file. Errors are ignored: the inbox then simply
        reports the next write."""
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                         OWNER_ONLY)
            os.close(fd)
            self._last_mtime = self.path.stat().st_mtime
        except OSError:
            self._last_mtime = 0.0

    def poll(self) -> Optional[str]:
        """Return the file's stripped content if it changed since the last poll.

        Returns:
            str | None: new non-empty content, or None.

        Raises:
            OSError: the file exists but cannot be read.
        """
        if not self.path.exists():
            return None
        mtime = self.path.stat().st_mtime
        if mtime <= self._last_mtime:
            return None
        self._last_mtime = mtime
        text = self.path.read_text().strip()
        return text or None


class SayVoice:
    """Speaks text with macOS `say`, without blocking.

    Args:
        voice: preferred voice name, or None to pick the best installed one.
        rate: words per minute, as a string for the command line.
        popen, run: subprocess callables, injectable for tests.
        log: logging callable.
    """

    def __init__(self, voice: Optional[str] = None, rate: str = DEFAULT_SAY_RATE, *,
                 popen: Callable = subprocess.Popen, run: Callable = subprocess.run,
                 log: LogFn = default_log):
        self.wanted = voice
        self.rate = rate
        self.popen = popen
        self.run = run
        self.log = log
        self.voice: Optional[str] = None

    def pick_voice(self) -> Optional[str]:
        """Choose the voice: the requested one if installed, else the first
        installed preference, else None (the system default).

        Side effects:
            Sets self.voice.
        """
        try:
            installed = self.run(["say", "-v", "?"], capture_output=True, text=True,
                                 timeout=VOICE_LIST_TIMEOUT_S).stdout
        except Exception:  # no `say` (not macOS) or it hung: use what was asked for
            self.voice = self.wanted
            return self.voice
        if self.wanted and self.wanted in installed:
            self.voice = self.wanted
        else:
            self.voice = next((v for v in VOICE_PREFERENCES if v in installed), None)
        return self.voice

    def speak(self, text: str) -> None:
        """Start speaking `text` in the background; failures are logged."""
        # "--" ends the options, so text that starts with "-" is spoken, not
        # read as a `say` option like -o (write a file) or -f (read one).
        cmd = ["say", "-r", self.rate] + (["-v", self.voice] if self.voice else []) + ["--", text]
        try:
            self.popen(cmd)
            self.log(f"[say] {text}")
        except Exception as exc:
            self.log(f"[say] failed: {exc}")
