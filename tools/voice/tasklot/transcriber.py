"""Transcribers: audio file -> text, all local.

Transcriber        whisper.cpp's `whisper-cli`, used by the live daemon. Never
                   raises: a missing binary, a hang, or a bad file gives "" and a
                   log line, because the daemon must keep running (E-01, E-06, E-07).
ScriptTranscriber  an external script named by TASKLOT_WHISPER_SCRIPT that takes
                   an audio path and prints the transcript; used by the offline
                   `voice` CLI for phone recordings. Raises on failure, because the
                   CLI should stop and say why.
FakeTranscriber    returns fixed text; replaces the mic and model in tests and in
                   the end-to-end test (TASKLOT_FAKE_TRANSCRIPT).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import DEFAULT_WHISPER_BIN, WHISPER_TIMEOUT_S
from .logs import LogFn, log as default_log

# A 16 kHz mono WAV header is 44 bytes; under this size the recording holds
# about a quarter second of audio, which is never a task (E-01).
MIN_WAV_BYTES = 8000

Runner = Callable[..., "subprocess.CompletedProcess"]


class TranscriptionError(Exception):
    """The offline transcriber failed; the message is meant for the user."""


def _collapse(text: str) -> str:
    """Join whisper's output lines into one space-separated string."""
    return " ".join((text or "").split()).strip()


class Transcriber:
    """Runs whisper-cli on a WAV file.

    Args:
        binary: whisper.cpp command name or path.
        model: path to a ggml model file.
        timeout: seconds before a hung run is abandoned.
        runner: subprocess.run-like callable, injectable for tests.
        which: shutil.which-like callable, injectable for tests.
        log: logging callable.
    """

    def __init__(self, binary: str = DEFAULT_WHISPER_BIN, model: str = "", *,
                 timeout: float = WHISPER_TIMEOUT_S, runner: Runner = subprocess.run,
                 which: Callable[[str], object] = shutil.which, log: LogFn = default_log):
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self.runner = runner
        self.which = which
        self.log = log

    def problems(self) -> list[str]:
        """Check the binary and the model up front, so a missing piece is
        reported once at startup instead of as a failure on every order (E-06).

        Returns:
            list[str]: human-readable problems; empty when ready.
        """
        found = []
        if not self.which(self.binary):
            found.append(f"{self.binary} not found on PATH (brew install whisper-cpp)")
        if not self.model or not os.path.exists(self.model):
            found.append(f"whisper model not found at {self.model!r} (set TASKLOT_WHISPER_MODEL)")
        return found

    def transcribe(self, path: Path) -> str:
        """Transcribe one recording.

        Args:
            path: the WAV file.

        Returns:
            str: the transcript on one line, or "" if the file is missing or
            too small, or whisper failed or timed out (all logged).
        """
        path = Path(path)
        if not path.exists() or path.stat().st_size < MIN_WAV_BYTES:
            self.log("[whisper] recording too short / empty")
            return ""
        try:
            result = self.runner([self.binary, "-m", self.model, "-f", str(path), "-nt", "--no-prints"],
                                 capture_output=True, text=True, timeout=self.timeout)
        except Exception as exc:  # FileNotFoundError, TimeoutExpired, ...
            self.log(f"[whisper] failed: {exc}")
            return ""
        return _collapse(result.stdout)


class ScriptTranscriber:
    """Runs an external transcriber script: `python3 <script> <audio>`.

    Args:
        script: path to the script.
        runner: subprocess.run-like callable, injectable for tests.
        log: logging callable (progress goes to stderr by default).
    """

    def __init__(self, script: str, *, runner: Runner = subprocess.run,
                 log: LogFn = lambda m: print(m, file=sys.stderr, flush=True)):
        self.script = script
        self.runner = runner
        self.log = log

    def transcribe(self, path: Path) -> str:
        """Transcribe one audio file.

        Raises:
            TranscriptionError: the script is unset or missing, or it failed.
        """
        if not self.script or not os.path.exists(self.script):
            raise TranscriptionError(
                f"TASKLOT_WHISPER_SCRIPT is unset or missing ({self.script!r})\n"
                "Set it to a transcriber script, or use --text to skip transcription.")
        self.log(f"  transcribing {Path(path).name} ...")
        result = self.runner([sys.executable, self.script, str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            raise TranscriptionError(f"whisper failed: {result.stderr.strip() or result.returncode}")
        return result.stdout.strip()


class FakeTranscriber:
    """Returns the same text for every file.

    Args:
        text: the transcript to return.
        log: logging callable.
    """

    def __init__(self, text: str, log: LogFn = default_log):
        self.text = text
        self.log = log

    def problems(self) -> list[str]:
        """Always ready."""
        return []

    def transcribe(self, path: Path) -> str:
        """Return the fixed text, whatever `path` is."""
        self.log("[whisper] (mock) " + self.text)
        return self.text
