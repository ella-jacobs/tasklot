#!/usr/bin/env python3
"""TaskLot ears -- the laptop half, local. No browser, no website.

Holds the serial port to the Mega. When a blank car passes the SPEAKER it
records from the mic; when that car is PARKED it stops, transcribes with local
whisper, condenses to 18 characters and sends `CAR n <text>` back so the real
text lands on the LCD. A loaded car returning to the speaker is read back aloud.

    python3 tools/voice/tasklot_ears.py

Nothing else may hold the port -- no Arduino Serial Monitor, no browser page.

Design notes worth keeping:
  * Transcription runs on a WORKER THREAD. It takes seconds, and the read loop
    must keep draining the port or the OS buffer overflows and lines arrive
    truncated -- which is how you get a garbled LCD.
  * Every write is paced and length-capped. The Mega's RX buffer is 64 bytes
    and printLot() blocks it ~135 ms at 9600 baud; one oversized write corrupts
    the screen just as badly as a burst.
  * The read loop never dies. Any exception is logged and swallowed.

Written with Claude (Anthropic) as a coding assistant, to Ella's design.
"""
import os, re, sys, time, queue, signal, threading, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from condense import condense, ascii_only, clip

import serial

PORT      = os.environ.get("TASKLOT_PORT", "/dev/cu.usbmodem101")
BAUD      = 9600
MODEL     = os.environ.get("TASKLOT_WHISPER_MODEL",
                         os.path.expanduser("~/.whisper-models/ggml-base.en.bin"))
MIC       = ":0"

# --- voice ----------------------------------------------------------------
# `say` defaults to a robotic legacy voice. Prefer a Premium/Enhanced one if
# it is installed (System Settings > Accessibility > Spoken Content > System
# Voice > Manage Voices). Override with TASKLOT_VOICE="Ava (Premium)".
VOICE_PREFS = ["Ava (Premium)", "Zoe (Premium)", "Evan (Premium)",
               "Allison (Premium)", "Samantha (Enhanced)", "Ava (Enhanced)",
               "Samantha"]
SAY_RATE  = os.environ.get("TASKLOT_RATE", "180")
SAY_PIPE  = "/tmp/tasklot_say.txt"   # write a line here and it is spoken
CMD_PIPE  = "/tmp/tasklot_cmd.txt"   # write a board command here and it is sent
                                     #   echo CLEAR  > /tmp/tasklot_cmd.txt
                                     #   echo RESET  > /tmp/tasklot_cmd.txt

def pick_voice():
    want = os.environ.get("TASKLOT_VOICE")
    try:
        have = subprocess.run(["say", "-v", "?"], capture_output=True,
                              text=True, timeout=10).stdout
    except Exception:
        return want
    if want and want in have:
        return want
    for v in VOICE_PREFS:
        if v in have:
            return v
    return None

VOICE = None
LCD_TEXT  = 18            # what fits after the "1>" priority marker

tasks    = {}             # car -> full task text (only what WE transcribed)
labels   = {}             # car -> the 18-char label the BOARD is showing
rec      = None           # live ffmpeg process
rec_car  = None
rec_t0   = 0.0            # when recording started -- see MIN_HOLD
MAX_REC  = 60.0           # s. A car that goes to the speaker and never parks
                          # would otherwise record until the daemon dies.
MIN_HOLD = 0.6            # s. Stopping ffmpeg inside its device-init window
                          # can silently yield NO file. Verified 19-trial.
jobs     = queue.Queue()  # (car, wav) handed to the transcription worker
write_lk = threading.Lock()
ser      = None

def log(*a): print(*a, flush=True)

# --- transcript cleanup ---------------------------------------------------
# whisper.cpp marks segment breaks with ">>" and faithfully transcribes throat-
# clearing. Feeding that straight to condense() puts "Hello. >> I need" on the
# LCD -- 18 characters of nothing. Strip the markers and the filler first.
FILLER = {"hello","hi","hey","okay","ok","um","uh","yeah","yes","no","thanks",
          "thank you","right","so","well","alright","all right","mm","hmm",
          "about","and","bye","goodbye"}

# Greetings survive as sentence PREFIXES too -- "Hello, I need to talk to..."
# is one comma-joined sentence, so segment filtering alone leaves it intact and
# the LCD shows "Hello, I need". Strip them off the front, repeatedly.
LEAD = (r"(?:(?:hello|hi|hey)(?:\s+there)?|okay|ok|um+|uh+|so|well|alright"
        r"|all right|yeah|mm+|hmm+|please|like|oh|ah|er|eh|huh|wait|anyway"
        r"|actually|basically)")

def strip_lead(s):
    prev = None
    while s and s != prev:
        prev = s
        s = re.sub(r"^\s*" + LEAD + r"\b[\s,.!?-]*", "", s, flags=re.I)
    return s.strip()

def clean_transcript(t):
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)      # [BLANK_AUDIO], (music)
    parts = [p.strip(" .,!?-") for p in re.split(r">>|\.\s+", t)]
    keep = []
    for p in parts:
        if not p: continue
        bare = re.sub(r"[^\w\s]", "", p).strip().lower()
        if not bare or bare in FILLER: continue
        p = strip_lead(p)
        if not p: continue
        keep.append(p.strip())
    if not keep:
        # If the whole thing was filler, return EMPTY -- the caller drops it.
        # `or flat` here handed back the untouched original ("Hello?"), which
        # defeated both the stripper and the empty-label guard.
        return strip_lead(" ".join(t.split()))
    out = []
    for k in keep:                       # whisper stutters across cuts
        if not any(k.lower() in o.lower() for o in out):
            out.append(k)
    return ". ".join(out).strip() + "."

def wav_for(car): return f"/tmp/tasklot_order_car{car}.wav"

# --- the LCD label --------------------------------------------------------
# Rules truncate from the front, so "homework due at midnight for engines 21"
# becomes "Homework due" -- it drops the only two things that matter. An LLM
# keeps the subject and the course code: "ENGS21 HW MIDNIGHT". Costs ~8s, which
# is fine here: the car is already parked and the label lands a beat later.
# Falls back to the rule-based condense() on any failure, so a slow or missing
# `claude` degrades the label instead of breaking the demo.
USE_LLM   = os.environ.get("TASKLOT_LLM", "1") != "0"
LLM_TMO   = float(os.environ.get("TASKLOT_LLM_TIMEOUT", "25"))

LLM_PROMPT = """Turn this spoken task into a label for a 20x4 character LCD.

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

# The prompt says "never add information". The model does it anyway -- it added
# TONIGHT to a task that never mentioned a time. Asking is not enough, so this
# checks. Any time/date word or digit in the label must actually appear in the
# transcript, or the label is rejected and the rule-based one stands.
# Abbreviations count: the model wrote FRI for a task that never said Friday,
# and \bfriday\b did not match it. Each entry is matched as a PREFIX, so "fri"
# catches FRI and FRIDAY, "tmr" catches TMRW and TOMORROW.
RISKY = ("tonight","tonite","tngt","tnght","tomorrow","tmrw","tmr","today",
         "midnight","midnite","mdnt","noon","morning","mrng","afternoon",
         "evening","evng","mon","tue","tues","wed","weds","thu","thur","thurs",
         "fri","sat","sun","week","wknd","weekend","asap","urgent","soon",
         "am","pm","due","deadline","late","latest")

STOP = {"the","a","an","to","for","of","and","or","my","me","i","is","it",
        "that","this","in","on","at","with","about","get","go","do"}

def unrelated(label, transcript):
    """Compression keeps at least one real word from what was said. Invention
    usually keeps none -- "How do you tell where that's going?" came back as
    "PLACE ORDER". Abbreviations count: a label word matches if it is a prefix
    of a transcript word, or vice versa (HW/homework, PROF/professor)."""
    lw = [w for w in re.findall(r"[a-z0-9]+", label.lower())
          if len(w) >= 2 and w not in STOP]
    tw = [w for w in re.findall(r"[a-z0-9]+", transcript.lower())
          if len(w) >= 2 and w not in STOP]
    if not lw or not tw:
        return False                       # nothing to judge on; let it pass
    for a in lw:
        for b in tw:
            if a == b or a.startswith(b[:3]) or b.startswith(a[:3]):
                return False
    return True

def invented(label, transcript):
    t = transcript.lower()
    lab = label.lower()
    for w in RISKY:
        # prefix match on a whole label word, so FRI and FRIDAY both trip "fri"
        if not re.search(r"\b" + w, lab):
            continue
        # allowed only if the transcript really contains that idea
        if re.search(r"\b" + w[:3], t):
            continue
        return w
    for d in re.findall(r"\d+", label):
        if d not in t:
            return d
    return None

def _fit(label, n):
    """An LLM label that is a word or two long is worth trimming, not binning."""
    if len(label) <= n:
        return label
    words = label.split()
    while words and len(" ".join(words)) > n:
        words.pop()
    out = " ".join(words)
    return out if out else label[:n].strip()

def llm_label(text):
    if not USE_LLM:
        return None
    # Every invention we have seen came from a transcript with nothing in it:
    # "Paper" -> PAPER DUE TONIGHT, "A lot" -> A LOT SORRY, "There you go,
    # maybe" -> TY FINAL PROJ. Asked to make a task label out of nothing, it
    # makes something up. So don't ask -- the rule-based label is honest here.
    content = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]
    if len(content) < 3:
        log(f"[llm] skipped -- too little was said ({len(content)} words)")
        return None
    try:
        r = subprocess.run(["claude", "-p", LLM_PROMPT % text],
                           capture_output=True, text=True, timeout=LLM_TMO)
        out = " ".join(r.stdout.split()).strip().strip('"\'').rstrip(".")
        out = ascii_only(out)
        if not out:
            return None
        if len(out) > LCD_TEXT:
            trimmed = _fit(out, LCD_TEXT)
            log(f"[llm] {out!r} was {len(out)} chars -> trimmed to {trimmed!r}")
            out = trimmed
        if unrelated(out, text):
            log(f"[llm] REJECTED {out!r} -- shares no word with what was said")
            return None
        bad = invented(out, text)
        if bad:
            log(f"[llm] REJECTED {out!r} -- invented {bad!r}, not in the recording")
            return None
        return out or None
    except Exception as e:
        log(f"[llm] failed ({type(e).__name__}) -- falling back to rules")
        return None

# --------------------------------------------------------------------------
def start_recording(car):
    global rec, rec_car, rec_t0
    # A car lingering on the speaker pad gets read again. Restarting would throw
    # away everything said so far, so a repeat trigger for the SAME car is
    # ignored and the original recording keeps running.
    if rec_car == car and rec and rec.poll() is None:
        log(f"[mic] CAR {car} re-read at the speaker -- keeping the recording")
        return
    if os.environ.get("TASKLOT_FAKE_TRANSCRIPT"):
        rec_car = car; log(f"[mic] (mock) recording for CAR {car}"); return
    stop_recording_proc()
    rec_car = car
    path = wav_for(car)
    try:
        rec = subprocess.Popen(
            ["ffmpeg", "-y", "-f", "avfoundation", "-i", MIC,
             "-ar", "16000", "-ac", "1", path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        rec_t0 = time.time()
        log(f"[mic] recording for CAR {car} -- park it to finish")
    except Exception as e:
        rec = None
        log(f"[mic] !! FAILED to start ffmpeg: {e}")

def stop_recording_proc():
    """Stop cleanly so ffmpeg writes a valid WAV trailer. SIGKILL leaves the
    RIFF header with placeholder sizes, which whisper reads as garbage."""
    global rec
    if not rec or rec.poll() is not None:
        rec = None; return
    held = time.time() - rec_t0
    if held < MIN_HOLD:
        time.sleep(MIN_HOLD - held)   # never stop inside ffmpeg's init window
    try:
        rec.communicate(input=b"q", timeout=3)          # graceful
    except Exception:
        try:
            rec.send_signal(signal.SIGINT)              # ffmpeg flushes on INT
            rec.wait(timeout=3)
        except Exception:
            try: rec.kill(); rec.wait(timeout=2)
            except Exception: pass
            log("[mic] !! had to SIGKILL ffmpeg -- WAV may be truncated")
    rec = None

def transcribe(path):
    fake = os.environ.get("TASKLOT_FAKE_TRANSCRIPT")
    if fake:
        log("[whisper] (mock) " + fake); return fake
    if not os.path.exists(path) or os.path.getsize(path) < 8000:
        log("[whisper] recording too short / empty"); return ""
    try:
        r = subprocess.run(
            ["whisper-cli", "-m", MODEL, "-f", path, "-nt", "--no-prints"],
            capture_output=True, text=True, timeout=90)
        return " ".join(r.stdout.split()).strip()
    except Exception as e:
        log(f"[whisper] failed: {e}"); return ""

def speak(text):
    try:
        cmd = ["say", "-r", SAY_RATE]
        if VOICE: cmd += ["-v", VOICE]
        subprocess.Popen(cmd + [text])
        log(f"[say] {text}")
    except Exception as e:
        log(f"[say] failed: {e}")

def cmd_pipe_watcher():
    """Send a board command without owning the port yourself.
    `RESET` is ours: forget every task the laptop knows AND clear the board,
    which is what you want between demo runs -- including any phantom car a
    partial RFID read invented."""
    try:
        open(CMD_PIPE, "w").close(); last = os.path.getmtime(CMD_PIPE)
    except Exception:
        last = 0.0
    while True:
        try:
            if os.path.exists(CMD_PIPE):
                m = os.path.getmtime(CMD_PIPE)
                if m > last:
                    last = m
                    cmd = open(CMD_PIPE).read().strip()
                    if not cmd:
                        pass
                    elif cmd.upper() == "RESET":
                        tasks.clear(); labels.clear()
                        send("CLEAR")
                        log("[reset] laptop memory wiped, board cleared")
                    else:
                        send(cmd)
        except Exception as e:
            log(f"[cmdpipe] !! {e}")
        time.sleep(0.4)

def rec_capper():
    """Close an order nobody ever parked, rather than holding the mic open."""
    global rec_car
    while True:
        time.sleep(1.0)
        try:
            if rec and rec_car is not None and (time.time() - rec_t0) > MAX_REC:
                car = rec_car
                log(f"[mic] CAR {car} never parked -- capping at {int(MAX_REC)}s")
                stop_recording_proc()
                rec_car = None
                jobs.put((car, wav_for(car)))
        except Exception as e:
            log(f"[capper] !! {e}")

def say_pipe_watcher():
    """Anything written to /tmp/tasklot_say.txt is spoken in the same voice.
    This is the hook for a live LLM: Claude watches the log and can put a
    better-phrased line here without the daemon needing to know about it."""
    # Start from the file's CURRENT mtime, and blank it -- otherwise a restart
    # re-speaks whatever was last written, out of nowhere.
    try:
        open(SAY_PIPE, "w").close()
        last = os.path.getmtime(SAY_PIPE)
    except Exception:
        last = 0.0
    while True:
        try:
            if os.path.exists(SAY_PIPE):
                m = os.path.getmtime(SAY_PIPE)
                if m > last:
                    last = m
                    line = open(SAY_PIPE).read().strip()
                    if line: speak(line)
        except Exception as e:
            log(f"[saypipe] !! {e}")
        time.sleep(0.4)

# --------------------------------------------------------------------------
def send(cmd):
    """One paced, capped, ASCII-only line. Never let a long or multi-byte
    string reach the board -- that is the 64-byte overrun, in one write."""
    with write_lk:
        try:
            ser.write((cmd + "\n").encode("ascii", "ignore"))
            ser.flush()
            time.sleep(0.35)
            log(f"[->board] {cmd}")
        except Exception as e:
            log(f"[->board] !! write failed: {e}")

def worker():
    while True:
        car, path = jobs.get()
        try:
            log("[whisper] transcribing...")
            text = transcribe(path)
            if not text:
                log(f"[task] CAR {car}: nothing transcribed"); continue
            text  = clean_transcript(text)
            log(f"[clean] -> {text!r}")
            # Cleaning can empty a non-empty transcript (all filler, or silence
            # whisper heard as "Okay"). Sending an empty label blanks the row.
            if not text.strip(" .,"):
                log(f"[task] CAR {car}: nothing left after cleanup -- not sending")
                continue
            c     = condense(text)
            full  = c.get("full") or text
            quick = clip(ascii_only(c.get("lcd") or text), LCD_TEXT)

            # TWO STAGES, on purpose.
            # 1. The rule-based label goes up IMMEDIATELY, ~0.6s after parking.
            #    The screen shows a real task instead of "CAR 3" while we think.
            # 2. The LLM label (~8s) replaces it if it is better. The wait reads
            #    as the label sharpening rather than as nothing happening.
            tasks[car]  = full
            labels[car] = quick
            log(f"[task] CAR {car}: {full!r} -> LCD {quick!r} (quick)")
            send(f"CAR {car} {quick}")

            better = llm_label(text)
            if better and better != quick:
                labels[car] = better
                log(f"[llm] CAR {car}: {quick!r} -> {better!r} (upgrade)")
                send(f"CAR {car} {better}")
            elif not better:
                log(f"[llm] CAR {car}: no upgrade, keeping {quick!r}")
        except Exception as e:
            log(f"[worker] !! {type(e).__name__}: {e}")
        finally:
            jobs.task_done()

# --------------------------------------------------------------------------
def handle(raw):
    global rec_car
    m = re.search(r"SPEAKER\s+CAR\s+(\d+)\s+ordering", raw)
    if m:
        start_recording(int(m.group(1))); return

    # NO SPOKEN PLAYBACK -- there is no separate playback area. Bringing a
    # loaded car back to the speaker says nothing out loud; it
    # puts the WHOLE task on the glass and pages through it. The board owns the
    # screen. Sent in <=40 char chunks because the AVR RX buffer is 64 bytes.
    m = re.search(r"CAR\s+(\d+)\s+reading back", raw)
    if m:
        car  = int(m.group(1))
        full = tasks.get(car) or labels.get(car)
        if not full:
            log(f"[show] CAR {car}: no text on the laptop -- nothing to show")
            return
        send("FULLCLR")
        words, line = full.split(), ""
        for w in words:
            if len(line) + len(w) + 1 > 40:
                send(f"FULL {line}"); line = w
            else:
                line = (line + " " + w).strip()
        if line: send(f"FULL {line}")
        send(f"FULLSHOW {car}")
        log(f"[show] CAR {car}: {full!r} on the glass")
        return

    m = re.search(r"SPACE\s+(\d+)\s*<-\s*CAR\s+(\d+)\s+parked", raw)
    if m:
        car = int(m.group(2))
        if rec_car == car:
            stop_recording_proc()
            path = wav_for(car)
            rec_car = None
            jobs.put((car, path))          # off this thread; keep draining serial
        return

    m = re.search(r"PICKUP\s+CAR\s+(\d+)\s+collected", raw)
    if m:
        car = int(m.group(1))
        tasks.pop(car, None); labels.pop(car, None)
        return

    # The board echoes what it stored; learn it so a restarted daemon can still
    # read a car back instead of claiming it is blank.
    m = re.search(r"TASK\s+(\d+)\s+(.+)", raw)
    if m:
        labels[int(m.group(1))] = m.group(2).strip(); return

def main():
    global ser
    ser = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(3)
    global VOICE
    VOICE = pick_voice()
    log(f"[voice] using {VOICE or 'system default (no premium voice installed)'}")
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=say_pipe_watcher, daemon=True).start()
    threading.Thread(target=rec_capper, daemon=True).start()
    threading.Thread(target=cmd_pipe_watcher, daemon=True).start()
    log(f"[ears] attached to {PORT}. Drive a car past the speaker to order.")
    while True:
        try:
            raw = ser.readline().decode(errors="replace").strip()
        except Exception as e:
            log(f"[serial] !! {e}"); time.sleep(1); continue
        if not raw:
            continue
        log(f"[board] {raw}")
        try:
            handle(raw)
        except Exception as e:
            log(f"[handle] !! {type(e).__name__}: {e} -- on line {raw!r}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_recording_proc(); log("\n[ears] stopped.")
