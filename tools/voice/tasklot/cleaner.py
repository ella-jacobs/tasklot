"""TranscriptCleaner: strip whisper.cpp noise before condensing.

whisper.cpp marks segment breaks with ">>", tags silence as [BLANK_AUDIO] and
noise as (music), and faithfully transcribes throat-clearing and greetings.
Feeding that straight to the Condenser puts "Hello. >> I need" on the LCD, which
is 18 characters of nothing. This runs between Transcriber and Condenser in the
live daemon (Ears).
"""
from __future__ import annotations

import re

# Whole segments that carry no task. A segment equal to one of these (after
# removing punctuation, lower-cased) is dropped.
FILLER_SEGMENTS = frozenset({
    "hello", "hi", "hey", "okay", "ok", "um", "uh", "yeah", "yes", "no", "thanks",
    "thank you", "right", "so", "well", "alright", "all right", "mm", "hmm",
    "about", "and", "bye", "goodbye",
})

# Greetings and filler also survive as sentence prefixes: "Hello, I need to talk
# to..." is one comma-joined segment, so segment filtering alone leaves "Hello,
# I need" on the LCD. These are stripped off the front repeatedly.
LEAD_WORDS = (r"(?:(?:hello|hi|hey)(?:\s+there)?|okay|ok|um+|uh+|so|well|alright"
              r"|all right|yeah|mm+|hmm+|please|like|oh|ah|er|eh|huh|wait|anyway"
              r"|actually|basically)")
LEAD = re.compile(r"^\s*" + LEAD_WORDS + r"\b[\s,.!?-]*", re.I)

# whisper.cpp annotations: [BLANK_AUDIO], [Music], (music), (coughs)
ANNOTATION = re.compile(r"\[[^\]]*\]|\([^)]*\)")
# Segment boundaries: whisper's speaker-change marker, or a sentence end.
SEGMENT_BREAK = re.compile(r">>|\.\s+")
SEGMENT_EDGE_CHARS = " .,!?-"


class TranscriptCleaner:
    """Removes annotations, filler segments, leading greetings, and stutters.

    Stateless; one instance can be shared across threads.
    """

    @staticmethod
    def strip_lead(text: str) -> str:
        """Strip leading greetings/filler words, repeatedly.

        Args:
            text: one segment.

        Returns:
            str: the segment without its leading filler, stripped.
        """
        prev = None
        while text and text != prev:
            prev = text
            text = LEAD.sub("", text, count=1)
        return text.strip()

    def clean(self, transcript: str) -> str:
        """Clean one raw transcript.

        Args:
            transcript: whisper output, possibly with markers and filler.

        Returns:
            str: the kept segments joined as sentences ("A. B."), or a string
            with no letters (often "") when everything was filler (E-02). The
            caller treats a result with nothing but punctuation as empty.
        """
        t = ANNOTATION.sub(" ", transcript)
        parts = [p.strip(SEGMENT_EDGE_CHARS) for p in SEGMENT_BREAK.split(t)]
        keep = []
        for part in parts:
            if not part:
                continue
            bare = re.sub(r"[^\w\s]", "", part).strip().lower()
            if not bare or bare in FILLER_SEGMENTS:
                continue
            part = self.strip_lead(part)
            if part:
                keep.append(part.strip())
        if not keep:
            # Everything was filler: return what is left after stripping, which
            # is empty or punctuation. Returning the original ("Hello?") here
            # once defeated the empty-label guard downstream.
            return self.strip_lead(" ".join(t.split()))
        out = []
        for segment in keep:
            # whisper repeats itself across segment cuts; keep the first copy.
            if not any(segment.lower() in o.lower() for o in out):
                out.append(segment)
        return ". ".join(out).strip() + "."

    @staticmethod
    def is_empty(cleaned: str) -> bool:
        """True when a cleaned transcript has nothing worth labelling.

        Sending an empty label would blank the car's LCD row, so the daemon
        sends nothing instead.
        """
        return not cleaned.strip(" .,")
