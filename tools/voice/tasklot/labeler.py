"""Labeler: an optional LLM label upgrade, behind hallucination guards.

The rule-based Condenser truncates from the front, so "homework due at midnight
for engines 21" becomes "Homework due", dropping the two things that matter. An
LLM keeps the subject and the course code ("ENGS21 HW MIDNITE"). It costs about
8 s, which is acceptable because the rule-based label is already on the LCD;
the better one replaces it a beat later.

The model is not trusted. Every label must pass guards that reject output that
shares no word with the transcript (unrelated) or adds a time, date, or number
that was never said (invented). Any failure, timeout, or rejection returns None
and the rule-based label stands.

The default runner shells out to the `claude` CLI (`claude -p <prompt>`), which
is what the project used. Tests pass a fake runner, so no test ever calls a model
or needs a key. Turn the upgrade off entirely with TASKLOT_LLM=0.
"""
from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional

from .condenser import LCD_TEXT, ascii_only
from .config import LLM_TIMEOUT_S
from .logs import LogFn, log as default_log

# Below this many content words the model has nothing to compress and invents
# instead: "Paper" came back as PAPER DUE TONIGHT, "A lot" as A LOT SORRY. The
# rule-based label is the honest one there, so the model is not asked.
MIN_CONTENT_WORDS = 3

# Two label and transcript words "match" if they are equal or one starts with the
# other's first three letters, so abbreviations like PROF/professor count.
# (HW/homework does not; a label made only of such words is rejected.)
PREFIX_MATCH_LEN = 3
MIN_GUARD_WORD_LEN = 2  # ignore one-letter words when judging relatedness

PROMPT = """Turn this spoken task into a label for a 20x4 character LCD.

HARD RULE: 18 characters or fewer, including spaces. Count them. If it is over
18, shorten it until it fits - drop "for class", "my", "the", articles, and any
word the label still reads fine without.

NEVER ADD INFORMATION. Only shorten what is actually there. Do not invent a
deadline, a time, a date, a course, or a person that the task does not mention.
If the task is one word, the label is that one word. Shortening is allowed;
adding is not.

Style: UPPERCASE. No quotes, no trailing period. Keep the SUBJECT and the
ACTION. Use standard course codes ONLY when a class is actually named (engines
21 / engs 21 -> ENGS21, comp sci -> COSC, AP computer science -> APCS). Prefer
the noun over the verb when space is tight.

Examples:
  homework due at midnight for engines 21  ->  ENGS21 HW MIDNITE
  reading, read a book for class           ->  READ BOOK
  I need to call the dentist               ->  CALL DENTIST
  email my professor about the project     ->  EMAIL PROF
  paper                                    ->  PAPER
  go to the gym with my roommate           ->  GYM W/ ROOMMATE

Output ONLY the label.

Task: %s"""

# Time and date words the model has added on its own despite the prompt: it
# wrote TONIGHT for a task that never mentioned a time, and FRI for one that
# never said Friday. Each entry matches as a prefix of a label word, so "fri"
# catches FRI and FRIDAY and "tmr" catches TMRW and TOMORROW.
RISKY_WORDS = ("tonight", "tonite", "tngt", "tnght", "tomorrow", "tmrw", "tmr", "today",
               "midnight", "midnite", "mdnt", "noon", "morning", "mrng", "afternoon",
               "evening", "evng", "mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs",
               "fri", "sat", "sun", "week", "wknd", "weekend", "asap", "urgent", "soon",
               "am", "pm", "due", "deadline", "late", "latest")

STOP_WORDS = frozenset({"the", "a", "an", "to", "for", "of", "and", "or", "my", "me", "i",
                        "is", "it", "that", "this", "in", "on", "at", "with", "about",
                        "get", "go", "do"})

Runner = Callable[[str, float], str]


def claude_cli_runner(prompt: str, timeout: float) -> str:
    """Run the prompt through the `claude` CLI and return its stdout.

    Args:
        prompt: the full prompt text.
        timeout: seconds before giving up.

    Returns:
        str: whatever the CLI printed.

    Raises:
        FileNotFoundError: the CLI is not installed.
        subprocess.TimeoutExpired: it took longer than `timeout`.
    """
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                            timeout=timeout)
    return result.stdout


def _words(text: str) -> list[str]:
    """Lower-case alphanumeric words of `text`."""
    return re.findall(r"[a-z0-9]+", text.lower())


def unrelated(label: str, transcript: str) -> bool:
    """True if the label shares no real word with the transcript.

    Compression keeps at least one word from what was said; invention usually
    keeps none ("How do you tell where that's going?" came back as PLACE ORDER).
    Abbreviations that keep the first three letters (PROF, PROJ) count as shared.

    Args:
        label: the candidate label.
        transcript: the cleaned transcript.

    Returns:
        bool: True to reject. False when either side has no content words,
        because there is nothing to judge on.
    """
    label_words = [w for w in _words(label) if len(w) >= MIN_GUARD_WORD_LEN and w not in STOP_WORDS]
    said_words = [w for w in _words(transcript) if len(w) >= MIN_GUARD_WORD_LEN and w not in STOP_WORDS]
    if not label_words or not said_words:
        return False
    for a in label_words:
        for b in said_words:
            if a == b or a.startswith(b[:PREFIX_MATCH_LEN]) or b.startswith(a[:PREFIX_MATCH_LEN]):
                return False
    return True


def invented(label: str, transcript: str) -> Optional[str]:
    """Return the first time/date word or number in the label that was never said.

    Args:
        label: the candidate label.
        transcript: the cleaned transcript.

    Returns:
        str | None: the offending risky word or digit string, or None if clean.
    """
    said = transcript.lower()
    lab = label.lower()
    for word in RISKY_WORDS:
        if not re.search(r"\b" + word, lab):
            continue
        # Allowed only if the transcript really contains that idea.
        if re.search(r"\b" + word[:PREFIX_MATCH_LEN], said):
            continue
        return word
    for digits in re.findall(r"\d+", label):
        if digits not in said:
            return digits
    return None


def fit(label: str, width: int) -> str:
    """Trim a too-long label word by word; an LLM label that is a word over is
    worth trimming, not binning. Falls back to a hard cut for one long word."""
    if len(label) <= width:
        return label
    words = label.split()
    while words and len(" ".join(words)) > width:
        words.pop()
    out = " ".join(words)
    return out if out else label[:width].strip()


def content_word_count(text: str) -> int:
    """Number of non-stop words, used to decide whether the model is worth asking."""
    return len([w for w in _words(text) if w not in STOP_WORDS])


class Labeler:
    """Asks an LLM for a better label and applies the guards.

    Args:
        runner: callable(prompt, timeout) -> str. Defaults to the `claude` CLI.
        enabled: False makes label() always return None without calling anything.
        timeout: seconds to wait for the runner.
        width: maximum label length.
        log: logging callable.
    """

    def __init__(self, runner: Runner = claude_cli_runner, enabled: bool = True,
                 timeout: float = LLM_TIMEOUT_S, width: int = LCD_TEXT,
                 log: LogFn = default_log):
        self.runner = runner
        self.enabled = enabled
        self.timeout = timeout
        self.width = width
        self.log = log

    def label(self, transcript: str) -> Optional[str]:
        """Return a guarded LLM label for the transcript, or None.

        Never raises: any runner error or timeout is logged and becomes None so
        the caller keeps the rule-based label (E-22).

        Args:
            transcript: the cleaned transcript.

        Returns:
            str | None: an ASCII label of at most `width` characters, or None if
            disabled, too little was said (E-23), the output was empty, or a
            guard rejected it (E-21).
        """
        if not self.enabled:
            return None
        count = content_word_count(transcript)
        if count < MIN_CONTENT_WORDS:
            self.log(f"[llm] skipped -- too little was said ({count} words)")
            return None
        try:
            raw = self.runner(PROMPT % transcript, self.timeout)
        except Exception as exc:  # any runner failure must fall back, never crash
            self.log(f"[llm] failed ({type(exc).__name__}) -- falling back to rules")
            return None
        # Collapse to one line, drop wrapping quotes and a trailing period.
        out = ascii_only(" ".join((raw or "").split()).strip().strip("\"'").rstrip("."))
        if not out:
            return None
        if len(out) > self.width:
            trimmed = fit(out, self.width)
            self.log(f"[llm] {out!r} was {len(out)} chars -> trimmed to {trimmed!r}")
            out = trimmed
        if unrelated(out, transcript):
            self.log(f"[llm] REJECTED {out!r} -- shares no word with what was said")
            return None
        bad = invented(out, transcript)
        if bad:
            self.log(f"[llm] REJECTED {out!r} -- invented {bad!r}, not in the recording")
            return None
        return out
