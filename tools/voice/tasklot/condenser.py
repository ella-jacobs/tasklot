"""Condenser: one spoken memo -> an 18-character LCD label.

The judgment half of the voice pipeline. Whisper turns audio into text; this
module decides what the text means and how to fit it on one line of a 20x4
character LCD (two characters go to the "1>" priority marker, leaving 18).

    full -> the whole task, however long (read-back, tasks.json, the simulator)
    lcd  -> what fits on one LCD line
    due  -> a due hint pulled out of the text ("friday", "4pm"), or ""
    raw  -> the ASCII-flattened input

condense.js is canonical for the browser and mirrors this class rule for rule.
Both are checked against tools/voice/cases.json, and a cross-language test feeds
the same inputs to both, so the LCD and the simulator can never quietly disagree
about what a memo said.

Used by Ears (live daemon) and the offline `voice` CLI command.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

LCD_WIDTH = 20   # characters per physical LCD line
LCD_TEXT = 18    # what is left after the "1>" priority marker
LCD_ROWS = 4     # one row per parking space; row order is priority order

# clip() only honours a word boundary if it keeps at least this share of the
# width; otherwise a hard cut keeps more of the task.
WORD_BOUNDARY_MIN_SHARE = 0.55

# devowel() only fires when the line misses by at most this many characters.
# Past that, squeezing vowels makes words unreadable and truncation is better.
DEVOWEL_MAX_OVER = 3
DEVOWEL_MIN_WORD = 5  # never squeeze a word shorter than this

# Loop caps. The leading-filler rule is anchored, so it fires once per pass, and
# intent prefixes stack ("I need to remember to ..."). These caps are well above
# anything seen in real transcripts and guarantee termination.
FILLER_PASSES = 4
INTENT_PASSES = 3

# ---------------------------------------------------------------------------
# Rule tables. Order matters in every list; keep them identical to condense.js.
# ---------------------------------------------------------------------------

# 1. Disfluency. Whisper transcribes every "um" faithfully.
FILLER = [
    re.compile(r"\b(um+|uh+|er+|ah+|hmm+|mm+)\b", re.I),
    re.compile(r"\b(you know|i mean|like i said|sort of|kind of|kinda|sorta)\b", re.I),
    re.compile(r"^\s*(ok(ay)?|so|alright|right|well|anyway|and)\b[,\s]*", re.I),
    re.compile(r"\b(basically|literally|honestly|actually|really|just)\b", re.I),
]

# 2. Intent prefixes. "I need to email the professor" is the task "Email the
#    professor". Longest alternatives first, so "I have got to" beats "I have".
INTENT = re.compile(
    r"^\s*(?:" + "|".join([
        r"note to self(?:,)?",
        r"reminder(?:,)?", r"remind me (?:to|that i (?:need|have) to)",
        r"don'?t forget (?:to|about)",
        r"i (?:really )?(?:need|have|ought|want|meant|forgot|gotta|got)\s*(?:to|ta)?",
        r"i'?ve (?:got|gotta) to", r"i'?m (?:going to|gonna)", r"i'?ll",
        r"i should", r"we (?:need|have) to", r"we should",
        r"make sure (?:that )?(?:i|we) ?(?:need to)?",
        r"remember to", r"todo(?::)?", r"task(?::)?", r"new task(?::)?",
    ]) + r")\b[,:\s]*", re.I)

# 3. When it is due. Pulled out of the text: the LCD has no room for it, and the
#    read-back and tasks.json show it as its own field.
DUE = [
    re.compile(r"\b(?:by|before|due|on)\s+(tomorrow morning|tomorrow night|tomorrow|tonight|today|this (?:morning|afternoon|evening|week|weekend)|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I),
    re.compile(r"\b(?:by|at|before)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I),
    re.compile(r"\b(?:by|before|on)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}/\d{1,2})\b", re.I),
    re.compile(r"\b(tomorrow (?:morning|afternoon|night)|tomorrow|tonight|today|this (?:morning|afternoon|evening|weekend)|next week)\b", re.I),
]

# 4. Where a sentence stops being the task and starts being the reason.
#    "Email the professor about whether we still need the poster" -> cut at "about".
CLAUSE = re.compile(r"\s+\b(?:about|because|since|so that|so|which|whether|that i|if i|but|and then|before i|after i|in order to|to see|to ask|to find out|for the (?:sake|reason))\b\s+", re.I)

# 5. LCD-only abbreviations. Conservative on purpose: a bad abbreviation reads
#    worse than an honest truncation.
ABBREV = [
    (re.compile(r"\bprofessors?\b", re.I), "Prof"), (re.compile(r"\bappointments?\b", re.I), "appt"),
    (re.compile(r"\bmeetings?\b", re.I), "mtg"), (re.compile(r"\bhomework\b", re.I), "HW"),
    (re.compile(r"\bassignments?\b", re.I), "asgmt"), (re.compile(r"\bpresentations?\b", re.I), "pres"),
    (re.compile(r"\bprojects?\b", re.I), "proj"), (re.compile(r"\bapplications?\b", re.I), "app"),
    (re.compile(r"\blaboratory\b", re.I), "lab"), (re.compile(r"\blibrary\b", re.I), "lib"),
    (re.compile(r"\bmessages?\b", re.I), "msg"), (re.compile(r"\bschedule\b", re.I), "sched"),
    (re.compile(r"\bquestions?\b", re.I), "Q"), (re.compile(r"\bminutes?\b", re.I), "min"),
    (re.compile(r"\btomorrow\b", re.I), "tmrw"), (re.compile(r"\bdeadline\b", re.I), "due"),
    (re.compile(r"\breservations?\b", re.I), "resv"), (re.compile(r"\bregistration\b", re.I), "reg"),
    (re.compile(r"\band\b", re.I), "&"), (re.compile(r"\bwith\b", re.I), "w/"),
    (re.compile(r"\bwithout\b", re.I), "w/o"), (re.compile(r"\bnumber\b", re.I), "#"),
    (re.compile(r"\bversus\b", re.I), "vs"),
]

ARTICLES = re.compile(r"\b(?:the|a|an|my|our)\s+", re.I)

# Trailing detail lives in prepositional phrases: "Print the reader coupon
# before class" -> "Print the reader coupon".
PREPS = ("about", "before", "after", "during", "against", "onto", "into",
         "for", "from", "with", "under", "over", "at", "in", "on", "to", "by", "re")

# A sentence end followed by a capital: where the second sentence starts.
SENTENCE_BREAK = re.compile(r"[.!?]\s+[A-Z]")

# The HD44780 character ROM is ASCII. Smart quotes and dashes would render as
# garbage blocks, so they are flattened before anything else.
SMART_PUNCTUATION = {"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u201c": '"',
                     "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "..."}

VOWELS = "aeiouAEIOU"

# ---------------------------------------------------------------------------
# The nudge: the last line of a read-back names the first physical move.
# Rule-based so it runs offline and gives the same answer every time, which
# makes a demo rehearsable. Specific patterns come before general ones.
# ---------------------------------------------------------------------------
NUDGE = [
    (re.compile(r"\b(gmail|email|e-mail|inbox|reply|write back)\b", re.I), "Just open Gmail and get started."),
    (re.compile(r"\b(call|phone|ring|voicemail)\b", re.I), "Just pick up the phone. It is a two-minute call."),
    (re.compile(r"\b(text|message|dm|slack)\b", re.I), "Open the thread and send one line."),
    (re.compile(r"\b(print|printer|coupon)\b", re.I), "The printer is right there. Go hit print."),
    (re.compile(r"\b(charge|battery|plug|outlet)\b", re.I), "Go plug it in. That is the whole task."),
    (re.compile(r"\b(pay|bill|invoice|venmo|rent)\b", re.I), "Open the app and pay it now."),
    (re.compile(r"\b(book|schedule|appointment|reserve|rsvp)\b", re.I), "Open the calendar and pick a time."),
    (re.compile(r"\b(submit|turn in|upload|hand in|send)\b", re.I), "Attach it and hit send."),
    (re.compile(r"\b(report|essay|draft|paper|write|writing)\b", re.I), "Open the doc and write one bad sentence."),
    (re.compile(r"\b(study|review|revise|practice|problem set|pset)\b", re.I), "Open it and do one problem."),
    (re.compile(r"\b(read|chapter|article|paper)\b", re.I), "Open it and read one page."),
    (re.compile(r"\b(buy|order|cart|groceries|pick up)\b", re.I), "Pull it up and add it to the cart."),
    (re.compile(r"\b(clean|tidy|laundry|dishes|trash|organize)\b", re.I), "Set a timer for five minutes and start."),
    (re.compile(r"\b(glue|cut|solder|wire|assemble|build|sand|paint)\b", re.I), "Get the parts out on the table."),
    (re.compile(r"\b(pack|laundry|bag)\b", re.I), "Put one thing in the bag."),
]
DEFAULT_NUDGE = "Start with the first small piece. That is all you have to do."

EMPTY_SPACE = "-"  # what an empty parking space shows on its LCD row


@dataclass(frozen=True)
class Condensed:
    """The result of condensing one memo.

    Attributes:
        full: the whole task as one cleaned sentence.
        lcd: at most `width` characters, for one LCD row.
        due: the due hint in lower case, or "".
        raw: the input after ASCII flattening.
    """

    full: str
    lcd: str
    due: str
    raw: str

    def to_dict(self) -> dict:
        """Return the fields as a dict in the order condense.js returns them."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Text helpers. Module-level because they are stateless and also used by the
# Labeler and Ears; the Condenser exposes them as static methods too.
# ---------------------------------------------------------------------------
def ascii_only(text) -> str:
    """Flatten text to printable ASCII on one line.

    Smart quotes and dashes become their ASCII forms; every other non-printable
    or non-ASCII character is dropped (so "cafe" with an accent becomes "caf"); runs of
    whitespace collapse to one space.

    Args:
        text: anything; None and other falsy values become "".

    Returns:
        str: the flattened, stripped text.
    """
    s = str(text or "")
    for fancy, plain in SMART_PUNCTUATION.items():
        s = s.replace(fancy, plain)
    s = "".join(c for c in s if " " <= c <= "~")
    return re.sub(r"\s+", " ", s).strip()


def tidy(s: str) -> str:
    """Collapse spaces, pull punctuation onto the previous word, and trim stray
    leading punctuation and trailing separators left behind by removals."""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"^[\s,.;:-]+", "", s)
    s = re.sub(r"[\s,;:]+$", "", s)
    return s.strip()


def sentence_case(s: str) -> str:
    """Upper-case the first character only; the rest is left as spoken."""
    return s[0].upper() + s[1:] if s else s


def clip(s: str, width: int) -> str:
    """Cut to `width` characters, preferring a word boundary.

    No ellipsis: the HD44780 has no glyph for it, and three dots would cost 3 of
    the 18 characters.

    Args:
        s: the text to cut.
        width: maximum length of the result.

    Returns:
        str: at most `width` characters, without trailing separators.
    """
    if len(s) <= width:
        return s
    cut = s[:width]
    space = cut.rfind(" ")
    # Only honour the word boundary if it does not throw away most of the line.
    if space >= int(width * WORD_BOUNDARY_MIN_SHARE):
        cut = cut[:space]
    return re.sub(r"[\s,.;:-]+$", "", cut)


def trim_phrases(s: str, width: int) -> str:
    """Drop trailing prepositional phrases, rightmost first, until `s` fits.

    Never cuts at word 0 or 1, so a two-word verb phrase always survives.

    Args:
        s: the text to shorten.
        width: target length.

    Returns:
        str: the shortened text, possibly still longer than `width`.
    """
    while len(s) > width:
        words = s.split(" ")
        cut = -1
        for i in range(len(words) - 2, 1, -1):
            if words[i].lower() in PREPS:
                cut = i
                break
        if cut < 0:
            return s
        s = " ".join(words[:cut])
    return s


def devowel(s: str, width: int) -> str:
    """Pull interior vowels out of the longest word when `s` misses by a hair.

    "Print reader coupon" (19) -> "Print reader coupn" (18). This keeps the noun
    that truncation would have thrown away whole.

    Args:
        s: the text to squeeze.
        width: target length.

    Returns:
        str: the squeezed text, or `s` unchanged if it already fits, misses by
        more than DEVOWEL_MAX_OVER, or its longest word is too short.
    """
    over = len(s) - width
    if over <= 0 or over > DEVOWEL_MAX_OVER:
        return s
    words = s.split(" ")
    # Longest word, latest one on a tie: trailing detail is safer to squash.
    pick = 0
    for i, word in enumerate(words):
        if len(word) >= len(words[pick]):
            pick = i
    word = words[pick]
    if len(word) < DEVOWEL_MIN_WORD:
        return s
    while over > 0:
        # Rightmost interior vowel: never the first or last character.
        cut = -1
        for j in range(len(word) - 2, 0, -1):
            if word[j] in VOWELS:
                cut = j
                break
        if cut < 0:
            break
        word = word[:cut] + word[cut + 1:]
        over -= 1
    words[pick] = word
    return " ".join(words)


def _strip_trailing_stops(s: str) -> str:
    """Remove trailing periods and whitespace (JS: s.replace(/[.\\s]+$/, ''))."""
    return re.sub(r"[.\s]+$", "", s)


class Condenser:
    """Shortens transcripts to LCD labels and renders the lot.

    Stateless apart from the width, so one instance can be shared across threads.

    Args:
        width: characters available for the label (default LCD_TEXT = 18).
    """

    ascii_only = staticmethod(ascii_only)
    clip = staticmethod(clip)

    def __init__(self, width: int = LCD_TEXT):
        self.width = width

    def condense(self, transcript) -> Condensed:
        """Turn one transcript into a Condensed task.

        Each squeeze stage runs only while the text is still too wide, so a short
        task is never abbreviated or devowelled.

        Args:
            transcript: raw whisper text; messy is expected. None is treated as "".

        Returns:
            Condensed: all fields "" if nothing printable was said.
        """
        raw = ascii_only(transcript)
        if not raw:
            return Condensed("", "", "", "")
        width = self.width

        t = self._strip_filler(raw)
        t, due = self._extract_due(t)
        t = self._strip_intent(t)

        # One task per memo: keep the first sentence. A break at index 0 is not a
        # sentence (condense.js tests `> 0`), so it is ignored.
        m = SENTENCE_BREAK.search(t)
        full = tidy(t[:m.start() + 1] if m and m.start() > 0 else t)
        full = sentence_case(_strip_trailing_stops(full))

        lcd = full
        if len(lcd) > width:                       # (a) cut the reason off the task
            c = CLAUSE.search(lcd)
            if c and c.start() > 0:
                lcd = tidy(lcd[:c.start()])
        if len(lcd) > width:                       # (b) trailing prepositional detail
            lcd = tidy(trim_phrases(lcd, width))
        if len(lcd) > width:                       # (c) abbreviate
            for pattern, short in ABBREV:
                lcd = pattern.sub(short, lcd)
            lcd = tidy(lcd)
        if len(lcd) > width:                       # (d) drop articles
            lcd = tidy(ARTICLES.sub("", lcd))
        if len(lcd) > width:                       # (e) squeeze vowels
            lcd = devowel(lcd, width)
        lcd = clip(sentence_case(lcd), width)      # (f) truncate

        return Condensed(full=full, lcd=lcd, due=due, raw=raw)

    @staticmethod
    def _strip_filler(t: str) -> str:
        """Remove disfluencies, looping because the anchored leading-filler rule
        fires once per pass and real output stacks them ("Um okay so I ...")."""
        for _ in range(FILLER_PASSES):
            before = t
            for pattern in FILLER:
                t = pattern.sub(" ", t)
            t = tidy(t)
            if t == before:
                break
        return t

    @staticmethod
    def _extract_due(t: str) -> tuple[str, str]:
        """Pull the first due hint out of `t` before later stages can eat it.

        Returns:
            tuple: (text without the hint, hint in lower case or "").
        """
        for pattern in DUE:
            m = pattern.search(t)
            if m:
                # Replace the first occurrence of the matched text, exactly as
                # condense.js's String.replace(string, ' ') does.
                return tidy(t.replace(m.group(0), " ", 1)), m.group(1).lower()
        return t, ""

    @staticmethod
    def _strip_intent(t: str) -> str:
        """Drop intent prefixes ("I need to", "remind me to"); they stack."""
        for _ in range(INTENT_PASSES):
            before = t
            t = tidy(INTENT.sub("", t))
            if t == before:
                break
        return t

    @staticmethod
    def first_step(text) -> str:
        """The nudge line for a task: the first physical move. Never empty."""
        t = ascii_only(text or "")
        for pattern, line in NUDGE:
            if pattern.search(t):
                return line
        return DEFAULT_NUDGE

    def playback(self, task) -> str:
        """What a read-back says: the task, its due hint if any, then the nudge.

        Args:
            task: a Condensed, Task, or dict with "full" and optional "due";
                None is allowed.

        Returns:
            str: one spoken string, or "" if there is nothing to read back.
        """
        full = _field(task, "full")
        if not full:
            return ""
        out = _strip_trailing_stops(full) + "."
        due = _field(task, "due")
        if due:
            out += " Due %s." % due
        return out + " " + self.first_step(full)

    @staticmethod
    def lot_lines(lot, width: int = LCD_WIDTH) -> list[str]:
        """Render the four LCD rows from the lot, in priority (space) order.

        Every row is padded to the full width, because a short write would leave
        the previous row's tail on the glass.

        Args:
            lot: up to four entries, each None, a label string, or an object/dict
                with `lcd` and/or `full`.
            width: physical row width (default LCD_WIDTH = 20).

        Returns:
            list[str]: exactly LCD_ROWS strings of exactly `width` characters.
        """
        rows = []
        for i in range(LCD_ROWS):
            item = lot[i] if lot and i < len(lot) else None
            if not item:
                text = EMPTY_SPACE
            elif isinstance(item, str):
                text = item
            else:
                text = _field(item, "lcd") or _field(item, "full") or EMPTY_SPACE
            rows.append(("%d>%s" % (i + 1, clip(ascii_only(text), width - 2))).ljust(width))
        return rows


def _field(obj, name: str) -> str:
    """Read `name` from a dict or an object, returning "" when absent or None."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return obj.get(name) or ""
    return getattr(obj, name, "") or ""
