#!/usr/bin/env python3
"""TaskLot — condense.py

Port of condense.js. **condense.js is canonical**; this exists so the offline
CLI (tasklot_voice.py) can do the same job without a browser. Both are checked
against cases.json by test_condense.js / test_condense.py — if you change a rule,
change it in BOTH files and run BOTH tests, or the LCD and the page start
disagreeing about what the same memo said.

One spoken memo -> {"full", "lcd", "due", "raw"}
  full -> the browser page   the whole task
  lcd  -> the LCD2004A        18 chars, because "n>" eats two of the twenty

AI disclosure: written with Claude (Anthropic) to Ella's spec. Credit it.
"""
import re

LCD_WIDTH = 20   # the physical display
LCD_TEXT = 18    # what's left after the "1>" priority marker

FILLER = [
    re.compile(r"\b(um+|uh+|er+|ah+|hmm+|mm+)\b", re.I),
    re.compile(r"\b(you know|i mean|like i said|sort of|kind of|kinda|sorta)\b", re.I),
    re.compile(r"^\s*(ok(ay)?|so|alright|right|well|anyway|and)\b[,\s]*", re.I),
    re.compile(r"\b(basically|literally|honestly|actually|really|just)\b", re.I),
]

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

DUE = [
    re.compile(r"\b(?:by|before|due|on)\s+(tomorrow morning|tomorrow night|tomorrow|tonight|today|this (?:morning|afternoon|evening|week|weekend)|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I),
    re.compile(r"\b(?:by|at|before)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I),
    re.compile(r"\b(?:by|before|on)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}/\d{1,2})\b", re.I),
    re.compile(r"\b(tomorrow (?:morning|afternoon|night)|tomorrow|tonight|today|this (?:morning|afternoon|evening|weekend)|next week)\b", re.I),
]

CLAUSE = re.compile(r"\s+\b(?:about|because|since|so that|so|which|whether|that i|if i|but|and then|before i|after i|in order to|to see|to ask|to find out|for the (?:sake|reason))\b\s+", re.I)

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

PREPS = ["about", "before", "after", "during", "against", "onto", "into",
         "for", "from", "with", "under", "over", "at", "in", "on", "to", "by", "re"]

_SMART = {"‘": "'", "’": "'", "ʼ": "'", "“": '"', "”": '"',
          "–": "-", "—": "-", "…": "..."}


def ascii_only(s):
    """HD44780 ROM is ASCII. Smart quotes render as garbage blocks on the LCD."""
    s = str(s or "")
    for k, v in _SMART.items():
        s = s.replace(k, v)
    s = "".join(c for c in s if " " <= c <= "~")
    return re.sub(r"\s+", " ", s).strip()


def tidy(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"^[\s,.;:-]+", "", s)
    s = re.sub(r"[\s,;:]+$", "", s)
    return s.strip()


def sentence_case(s):
    return s[0].upper() + s[1:] if s else s


def clip(s, n):
    """Cut to n chars, preferring a word boundary — but not if that throws away
    most of the line. No ellipsis: the LCD has no '...' glyph worth 3 of 18 chars."""
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    if sp >= int(n * 0.55):
        cut = cut[:sp]
    return re.sub(r"[\s,.;:-]+$", "", cut)


def trim_phrases(s, width):
    """Drop trailing prepositional phrases, rightmost first. Never below two words."""
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


def devowel(s, width):
    """Missing by a character or three: pull interior vowels out of the longest
    word. 'Print reader coupon' (19) -> 'Print reader coupn' (18). Keeps the noun
    that truncation would have thrown away whole."""
    over = len(s) - width
    if over <= 0 or over > 3:
        return s
    words = s.split(" ")
    pick = 0
    for i, w in enumerate(words):
        if len(w) >= len(words[pick]):
            pick = i
    w = words[pick]
    if len(w) < 5:
        return s
    while over > 0:
        cut = -1
        for j in range(len(w) - 2, 0, -1):
            if w[j] in "aeiouAEIOU":
                cut = j
                break
        if cut < 0:
            break
        w = w[:cut] + w[cut + 1:]
        over -= 1
    words[pick] = w
    return " ".join(words)


def condense(transcript, width=LCD_TEXT):
    """The whole job. Returns {"full", "lcd", "due", "raw"}."""
    raw = ascii_only(transcript)
    if not raw:
        return {"full": "", "lcd": "", "due": "", "raw": ""}

    # -- disfluency. Looped: the leading rule is anchored and fires once a pass,
    #    and real whisper output stacks them ("Um okay so I really need to").
    t = raw
    for _ in range(4):
        before = t
        for f in FILLER:
            t = f.sub(" ", t)
        t = tidy(t)
        if t == before:
            break

    # -- the due hint, pulled out before anything else eats it
    due = ""
    for d in DUE:
        m = d.search(t)
        if m:
            due = m.group(1).lower()
            t = tidy(t[:m.start()] + " " + t[m.end():])
            break

    # -- intent prefix ("I need to ..."). Looped, they stack too.
    for _ in range(3):
        before = t
        t = tidy(INTENT.sub("", t))
        if t == before:
            break

    # -- one task per memo: keep the first sentence
    m = re.search(r"[.!?]\s+[A-Z]", t)
    full = tidy(t[:m.start() + 1] if m else t)
    full = sentence_case(re.sub(r"[.\s]+$", "", full))

    # -- squeeze, in stages, until it fits
    lcd = full
    if len(lcd) > width:                                    # (a) cut the reason off the task
        c = CLAUSE.search(lcd)
        if c and c.start() > 0:
            lcd = tidy(lcd[:c.start()])
    if len(lcd) > width:                                    # (b) trailing prepositional detail
        lcd = tidy(trim_phrases(lcd, width))
    if len(lcd) > width:                                    # (c) abbreviate
        for pat, rep in ABBREV:
            lcd = pat.sub(rep, lcd)
        lcd = tidy(lcd)
    if len(lcd) > width:                                    # (d) drop articles
        lcd = tidy(ARTICLES.sub("", lcd))
    if len(lcd) > width:                                    # (e) squeeze vowels
        lcd = devowel(lcd, width)
    lcd = clip(sentence_case(lcd), width)                   # (f) truncate

    return {"full": full, "lcd": lcd, "due": due, "raw": raw}


# ---------------------------------------------------------------------------
# THE NUDGE — the line the speaker adds when it reads a task back.
#
# Playing the task back verbatim is just a recording. The point of driving up to
# the speaker is that you are about to DO the thing, so the last line names the
# first physical move: "just open Gmail and get started." Small, concrete, and
# impossible to argue with — which is why it works on a brain avoiding the task.
#
# Rule-based on purpose: offline, no model, same answer every time so a demo is
# rehearsable. Order matters — specific patterns are tested before general ones.
#
# ** KEEP THIS IN LOCKSTEP WITH condense.js. ** Same patterns, same strings, same
# order. test_condense.py checks the pair.
# ---------------------------------------------------------------------------
NUDGE = [
    (re.compile(r"\b(gmail|email|e-mail|inbox|reply|write back)\b", re.I), "Just open Gmail and get started."),
    (re.compile(r"\b(call|phone|ring|voicemail)\b", re.I),                 "Just pick up the phone. It is a two-minute call."),
    (re.compile(r"\b(text|message|dm|slack)\b", re.I),                     "Open the thread and send one line."),
    (re.compile(r"\b(print|printer|coupon)\b", re.I),                      "The printer is right there. Go hit print."),
    (re.compile(r"\b(charge|battery|plug|outlet)\b", re.I),                "Go plug it in. That is the whole task."),
    (re.compile(r"\b(pay|bill|invoice|venmo|rent)\b", re.I),               "Open the app and pay it now."),
    (re.compile(r"\b(book|schedule|appointment|reserve|rsvp)\b", re.I),    "Open the calendar and pick a time."),
    (re.compile(r"\b(submit|turn in|upload|hand in|send)\b", re.I),        "Attach it and hit send."),
    (re.compile(r"\b(report|essay|draft|paper|write|writing)\b", re.I),    "Open the doc and write one bad sentence."),
    (re.compile(r"\b(study|review|revise|practice|problem set|pset)\b", re.I), "Open it and do one problem."),
    (re.compile(r"\b(read|chapter|article|paper)\b", re.I),                "Open it and read one page."),
    (re.compile(r"\b(buy|order|cart|groceries|pick up)\b", re.I),          "Pull it up and add it to the cart."),
    (re.compile(r"\b(clean|tidy|laundry|dishes|trash|organize)\b", re.I),  "Set a timer for five minutes and start."),
    (re.compile(r"\b(glue|cut|solder|wire|assemble|build|sand|paint)\b", re.I), "Get the parts out on the table."),
    (re.compile(r"\b(pack|laundry|bag)\b", re.I),                          "Put one thing in the bag."),
]

DEFAULT_NUDGE = "Start with the first small piece. That is all you have to do."


def first_step(text):
    """The nudge for one task. Always returns something."""
    t = ascii_only(text or "")
    for pattern, line in NUDGE:
        if pattern.search(t):
            return line
    return DEFAULT_NUDGE


def playback(task):
    """What the speaker SAYS when a loaded car pulls up — the whole read-back.

    Task, then when it is due if a due date was heard, then the nudge.
    Returns '' if there is nothing to read back.
    """
    full = (task or {}).get("full", "")
    if not full:
        return ""
    out = full.rstrip(". ") + "."
    due = (task or {}).get("due", "")
    if due:
        out += " Due %s." % due
    return out + " " + first_step(full)


def lot_lines(lot, width=LCD_WIDTH):
    """The four LCD lines. Space order IS priority order: space 1 is the top of
    the list, so moving a car moves the task. Every line is padded to the full
    width — a short write leaves the previous line's tail on screen otherwise."""
    out = []
    for i in range(4):
        item = lot[i] if lot and i < len(lot) else None
        if not item:
            text = "-"
        elif isinstance(item, str):
            text = item
        else:
            text = item.get("lcd") or item.get("full") or "-"
        out.append(("%d>%s" % (i + 1, clip(ascii_only(text), width - 2))).ljust(width))
    return out


if __name__ == "__main__":
    import sys, json
    text = " ".join(sys.argv[1:]) or sys.stdin.read()
    print(json.dumps(condense(text), indent=2))
