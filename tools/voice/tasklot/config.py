"""Settings: every tunable of the voice pipeline in one place.

Values come from environment variables so the daemon runs on any machine without
editing code; the CLI can override some of them with flags. Nothing here holds a
personal path: defaults are the macOS serial device name, a model path under the
current user's home, and /tmp for scratch files.

| Variable                 | Default                               | Meaning                               |
|--------------------------|---------------------------------------|---------------------------------------|
| TASKLOT_PORT             | /dev/cu.usbmodem101                   | serial device of the Mega             |
| TASKLOT_RESET_DELAY      | 3.0                                   | s to wait after opening (DTR reset)   |
| TASKLOT_MIC              | :0                                    | ffmpeg avfoundation audio input       |
| TASKLOT_WHISPER_BIN      | whisper-cli                           | whisper.cpp command                   |
| TASKLOT_WHISPER_MODEL    | ~/.whisper-models/ggml-base.en.bin    | whisper.cpp model                     |
| TASKLOT_WHISPER_SCRIPT   | (unset)                               | transcriber script for the voice CLI  |
| TASKLOT_LLM              | 1                                     | 0 turns the LLM label upgrade off     |
| TASKLOT_LLM_TIMEOUT      | 25                                    | s before the LLM is abandoned         |
| TASKLOT_VOICE            | (best installed)                      | macOS `say` voice                     |
| TASKLOT_RATE             | 180                                   | `say` words per minute                |
| TASKLOT_REC_DIR          | /tmp                                  | where order recordings are written    |
| TASKLOT_SAY_FILE         | /tmp/tasklot_say.txt                  | text written here is spoken           |
| TASKLOT_CMD_FILE         | /tmp/tasklot_cmd.txt                  | a board command written here is sent  |
| TASKLOT_TASKS_FILE       | tools/voice/tasks.json                | offline CLI task store                |
| TASKLOT_FAKE_TRANSCRIPT  | (unset)                               | skip mic + whisper, use this text     |
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

VOICE_DIR = Path(__file__).resolve().parent.parent

BAUD = 9600              # the firmware's Serial.begin rate
MAX_CARS = 8             # firmware MAX_CARS: a ninth UID is ignored until reset
SPACES = 4               # parking spaces, one LCD row each

# Pacing between serial writes. The Mega's RX buffer is 64 bytes and printLot()
# blocks for about 135 ms at 9600 baud, so back-to-back lines merge on the board
# ("3>Charge baCAR 4 Glu" on the bench). 0.35 s is what ran reliably.
SEND_PACING_S = 0.35

# Opening the port toggles DTR and resets the Mega; anything sent during its
# boot is lost. 3 s covers the bootloader and the reader self-test.
RESET_DELAY_S = 3.0

# A car that goes to the speaker and is never parked would otherwise hold the
# mic open until the daemon dies (E-08).
MAX_RECORDING_S = 60.0

# Stopping ffmpeg inside its device-initialisation window can produce no file
# at all; 0.6 s was enough in 19 bench trials (E-03).
MIN_HOLD_S = 0.6

WHISPER_TIMEOUT_S = 90.0   # a hung whisper gives up and yields "" (E-07)
LLM_TIMEOUT_S = 25.0

DEFAULT_PORT = "/dev/cu.usbmodem101"
DEFAULT_MODEL = "~/.whisper-models/ggml-base.en.bin"
DEFAULT_TMP = "/tmp"


class ConfigError(ValueError):
    """An environment variable has a value that cannot be used."""


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    """Read a float variable, naming the variable if it is malformed.

    Raises:
        ConfigError: the value is not a number.
    """
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a number") from None


@dataclass
class Settings:
    """All runtime configuration. Build with Settings.from_env()."""

    port: str = DEFAULT_PORT
    baud: int = BAUD
    reset_delay: float = RESET_DELAY_S
    pacing: float = SEND_PACING_S
    mic: str = ":0"
    whisper_bin: str = "whisper-cli"
    whisper_model: str = DEFAULT_MODEL
    whisper_script: str = ""
    whisper_timeout: float = WHISPER_TIMEOUT_S
    llm_enabled: bool = True
    llm_timeout: float = LLM_TIMEOUT_S
    voice: Optional[str] = None
    say_rate: str = "180"
    max_recording: float = MAX_RECORDING_S
    min_hold: float = MIN_HOLD_S
    rec_dir: Path = Path(DEFAULT_TMP)
    say_file: Path = Path(DEFAULT_TMP) / "tasklot_say.txt"
    cmd_file: Path = Path(DEFAULT_TMP) / "tasklot_cmd.txt"
    tasks_file: Path = field(default_factory=lambda: VOICE_DIR / "tasks.json")
    fake_transcript: str = ""

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        """Build Settings from environment variables (see the module docstring).

        Args:
            env: mapping to read; defaults to os.environ.

        Returns:
            Settings: with "~" expanded in the model path.

        Raises:
            ConfigError: a numeric variable is malformed.
        """
        env = os.environ if env is None else env
        tmp = env.get("TASKLOT_REC_DIR") or DEFAULT_TMP
        return cls(
            port=env.get("TASKLOT_PORT") or DEFAULT_PORT,
            reset_delay=_float(env, "TASKLOT_RESET_DELAY", RESET_DELAY_S),
            mic=env.get("TASKLOT_MIC") or ":0",
            whisper_bin=env.get("TASKLOT_WHISPER_BIN") or "whisper-cli",
            whisper_model=os.path.expanduser(env.get("TASKLOT_WHISPER_MODEL") or DEFAULT_MODEL),
            whisper_script=env.get("TASKLOT_WHISPER_SCRIPT", ""),
            llm_enabled=env.get("TASKLOT_LLM", "1") != "0",
            llm_timeout=_float(env, "TASKLOT_LLM_TIMEOUT", LLM_TIMEOUT_S),
            voice=env.get("TASKLOT_VOICE") or None,
            say_rate=env.get("TASKLOT_RATE") or "180",
            rec_dir=Path(tmp),
            say_file=Path(env.get("TASKLOT_SAY_FILE") or Path(DEFAULT_TMP) / "tasklot_say.txt"),
            cmd_file=Path(env.get("TASKLOT_CMD_FILE") or Path(DEFAULT_TMP) / "tasklot_cmd.txt"),
            tasks_file=Path(env.get("TASKLOT_TASKS_FILE") or VOICE_DIR / "tasks.json"),
            fake_transcript=env.get("TASKLOT_FAKE_TRANSCRIPT", ""),
        )
