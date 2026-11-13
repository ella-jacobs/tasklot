# TaskLot — design

This document describes how TaskLot works today, the exact serial protocol between the
board and the laptop, the edge cases and failure modes the system has to handle, and the
target object-oriented structure for the refactor. The edge-case section is the test
spec: every refactored component should have tests that pin the behaviour described
there, or a written reason why it cannot be tested automatically.

Source of truth for "current behaviour" is the code at the time of import:
`firmware/tasklot_full_v2/tasklot_full_v2.ino`, `tools/voice/tasklot_ears.py`,
`tools/voice/condense.{js,py}`, `tools/voice/tasklot_voice.py`, and
`tools/sim/tasklot-sim.html`.

**Status.** The refactor described in section 6 is done. Sections 3 to 5 (and the
"Today" column of every edge case) describe the code as it was imported, before the
refactor; section 6.4 records how the voice pipeline was actually built and which
"Fix" items changed, and [`firmware/README.md`](firmware/README.md) does the same for
the firmware (architecture, memory use, and the original's quirks, kept or fixed).

---

## 1. The interaction

TaskLot is a toy parking lot where each toy car is one task.

1. **Order.** Drive a blank car past the **speaker** reader. The board announces it, the
   laptop starts recording from the microphone, and the LCD flashes `ORDER IN PROGRESS`.
2. **Park.** Put the car down in one of four **spaces**. Coming to rest ends the order;
   there is no stop button. The laptop stops recording, transcribes, shortens the task to
   18 characters, and sends it to the board. The LCD flashes `ORDER IS IN`, then shows the
   lot.
3. **Priority is position.** The LCD shows the four spaces top to bottom: space 1 is line
   1. Moving a car to another space reorders the list.
4. **Read back.** Drive a car that already has a task past the speaker. The LCD shows
   `YOUR ORDER` with the whole task, paged three lines at a time.
5. **Done.** Drive the car through the **pickup lane** reader. Its task is cleared, its
   space is released, and the LCD flashes `ALL DONE!!`. The car is a blank key again.

The RFID sticker under each car stores nothing; it is a key. The board maps
UID -> car number, and car number -> 18-character label. The laptop holds the full text.

---

## 2. System overview

```
  NTAG213 sticker under each car
            |
            v
  6 x RC522 readers on one SPI bus            LCD2004A (20 x 4) on an I2C backpack
  (4 spaces, speaker lane, pickup lane)                 ^
            |                                           |
            v                                           |
  Arduino Mega 2560 running firmware/tasklot_full_v2 ---+
            |  ^
   events   |  |  commands        USB serial, 9600 baud, one line per message
            v  |
  Laptop: tools/voice/tasklot_ears.py
            |
            +-- ffmpeg (records the mic to a 16 kHz mono WAV)
            +-- whisper.cpp `whisper-cli` (local transcription)
            +-- clean_transcript() -> condense() (rule-based, 18-char label)
            +-- optional `claude -p` label upgrade, with hallucination guards

  Alternative laptop sides, same protocol:
    tools/sim/tasklot-sim.html   browser simulator; can also drive a real board over Web Serial
    tools/voice/tasklot_voice.py offline CLI: audio file or typed text -> tasks.json -> board
```

**The board never handles audio.** It has no microphone, the 3.3 V rail is already over
its rating with the readers, and the label only needs 18 ASCII characters. The laptop does
all recording, transcription and shortening.

### Hardware facts the software depends on

| Fact | Value | Where it matters |
|---|---|---|
| Board | Elegoo Mega 2560 | Pin map, 8 KB SRAM, 4 KB EEPROM |
| Readers | 6 x RC522, shared SCK 52 / MOSI 51 / MISO 50, shared RST A0 | Resetting one resets all |
| Space SS pins | 44, 45, 40, 41 (spaces 1-4) | `SS_PIN1..4` |
| Lane SS pins | speaker = 37, pickup = 36 in code (see open question 9.1) | `SS_SPEAKER`, `SS_PICKUP` |
| LCD | LCD2004A, I2C backpack at 0x27 or 0x3F, SDA 20 / SCL 21, 5 V | Scanned at boot |
| Serial | 9600 baud, AVR RX buffer 64 bytes | Pacing (section 3.4) |
| 3.3 V rail | Rated 50 mA; six RC522s draw 78-156 mA | Flaky reads under load |
| Tags | NTAG213, 7-byte UIDs | UID plausibility filter |

---

## 3. Serial protocol (as the current code uses it)

9600 baud, 8N1. Every message is one line. The board ends lines with `\r\n`
(`Serial.println`); the laptop sends `\n`. The board ignores `\r` on input.

Spacing is part of the format: the firmware prints **two spaces** after the space number
and after `SPEAKER`, and **three spaces** after `PICKUP`, so the columns line up in a
serial monitor. Parsers on the laptop use `\s+` and must keep doing so.

Car numbers on the wire are **1-based** (`CAR 1` is the first car registered). Space
numbers are 1-4.

### 3.1 Board -> laptop: events

| Line (exact format) | When | Who parses it |
|---|---|---|
| `* NEW CAR registered -> CAR <n>   UID <hex bytes> ` | First sighting of a plausible new UID, on any reader. UID bytes are two-digit uppercase hex, each followed by a space. | sim (log only) |
| `SPACE <s>  <- CAR <n> parked` | A car arrives on space `s`. | ears (stops recording if `n` is recording), sim |
| `SPACE <s>  -> CAR <n> left` | A space goes quiet for `GONE_MS`, or the car arrived somewhere else, or it was collected. | sim |
| `SPEAKER  CAR <n> ordering` | A **blank** car passes the speaker. | ears (starts recording), sim |
| `PLAYBACK CAR <n> reading back` | A car **with a label** passes the speaker. | ears (sends the full text), sim |
| `PICKUP   CAR <n> collected` | Any car passes the pickup lane. | ears (forgets the car's text), sim |
| `TASK <n> <label>` | Echo after `CAR`, `DONE`, or a pickup. After `DONE`/pickup the label is empty: the line is `TASK <n> ` with a trailing space. | ears (learns the label) |
| `PONG` | Reply to `PING`. | sim (link check) |
| `--------------------` | 20 dashes; opens and closes every lot printout. | sim (pacing: two rule lines = command finished) |
| `<s>><text>` | Four lot lines between the rules, e.g. `1>Email the Prof`, `2>-`, `3>CAR 4`. `-` = empty space; `CAR <n>` = parked car with no label. Text is at most 18 characters. | sim |
| `* tasks cleared` | After `CLEAR`. | none |
| `* bad car number: <n>` | A command named a car outside 1..8 (including non-numbers, which `atoi` reads as 0). | none |
| `* unknown command: <line>` | Anything unrecognised. | none |
| `  no car slots left - reset the board to clear` | A ninth distinct UID was seen (`MAX_CARS = 8`). | none |
| `* ignored a bad read (truncated UID): <hex> ` | A UID failed `plausibleUID()`. | none |
| `* EEPROM forgotten - reset the board to start clean` / `* REMEMBER is off - nothing is saved` | After `FORGET`. | none |
| Boot banner | `=== TaskLot v2 - four spaces, a speaker, a pickup lane ===`, one `space <k> reader (SS <pin>): 0x<ver>   <verdict>` line per space, `speaker reader (...)`, `pickup  reader (...)`, the rail hint, `LCD: 0x27` or the no-LCD message, optional `EEPROM:` line, three help lines, then a lot printout. | humans |

Reader version verdicts: `0x91`/`0x92` = `ok - genuine`, `0x88`/`0x12` = `ok - clone`,
`0x00`/`0xFF` = `<-- NOT TALKING`, anything else = `?? unexpected, but answering`.

### 3.2 Laptop -> board: commands

Commands are matched by **prefix** (`strncmp`), so `LOTS` behaves as `LOT` and `PINGX` as
`PING`. The input buffer is 48 bytes: lines longer than 47 characters are truncated, not
rejected.

| Command | Effect | Reply |
|---|---|---|
| `PING` | none | `PONG` |
| `LOT` | Ends any read-back overlay and reprints the lot. | lot printout |
| `CAR <n> <text>` | Sets car `n`'s label to the first 18 characters of `text` (stored byte-for-byte, no ASCII filtering). Works before the car has ever been seen. `CAR <n>` with no text blanks the label. | `TASK <n> <label>` + lot |
| `DONE <n>` | Blanks car `n`'s label, closes any order or read-back. Flashes `ALL DONE!!` only if the car had a label. | `TASK <n> ` + lot |
| `CLEAR` | Blanks every label and the full-text buffer. Car UIDs are kept. | `* tasks cleared` + lot |
| `FORGET` | Invalidates the EEPROM copy (only meaningful with `REMEMBER 1`). | message |
| `ORDER <n>` | Same code path as a blank car passing the speaker (for the simulator). If car `n` has a label this becomes a read-back. | `SPEAKER ...` or `PLAYBACK ...` + lot |
| `PLAY <n>` | Shows the read-back overlay for car `n` without a timeout. | lot |
| `FULLCLR` | Clears the full-text buffer. | none |
| `FULL <chunk>` | Appends `chunk` to the full-text buffer, with a space between chunks, up to 120 characters. Chunks should be at most 40 characters. | none |
| `FULLSHOW <n>` | Word-wraps the buffer into up to 9 rows of 20 and shows them for car `n`, 3 rows per page, 2.5 s per page, for 12 s. | lot |

The simulator also sends `PARK <s> <n>`, `LEAVE <s>` and `EMPTY`. Only the historical
`firmware/history/lcd_bridge` understands those; v2 answers `* unknown command:` (see
edge case E-30).

### 3.3 Typical exchange (order -> park -> label)

```
board  SPEAKER  CAR 3 ordering          ears starts ffmpeg for car 3
board  (lot printout)
board  SPACE 2  <- CAR 3 parked         ears stops ffmpeg, queues the WAV for car 3
board  (lot printout: 2>CAR 3)
laptop CAR 3 Email the Prof             rule-based label, ~0.6 s after parking
board  TASK 3 Email the Prof
board  (lot printout: 2>Email the Prof)
laptop CAR 3 EMAIL PROF RE POSTER       optional LLM upgrade, ~8 s later
board  TASK 3 EMAIL PROF RE POSTER
```

Read-back of a loaded car:

```
board  PLAYBACK CAR 3 reading back
laptop FULLCLR
laptop FULL Email the professor about whether we       (<= 40 chars per chunk)
laptop FULL still need the poster
laptop FULLSHOW 3
```

### 3.4 Pacing

The AVR RX buffer is 64 bytes, and `printLot()` blocks for about 135 ms writing six lines
at 9600 baud. A burst of commands overruns the buffer and two commands merge (seen on the
bench as `3>Charge baCAR 4 Glu`). So every sender paces:

| Sender | Pacing |
|---|---|
| `tasklot_ears.py` | One line per `send()`, under a lock, then `sleep(0.35)`. Non-ASCII is dropped by `encode("ascii", "ignore")`. |
| `tasklot-sim.html` | A queue; the next line goes only after the board's reply ends (two rule lines, or `PONG`), or after 1.2 s. |
| `tasklot_voice.py --push` | `sleep(0.08)` between lines (too short; see E-31). |

Opening the serial port toggles DTR and **resets the Mega**. Every sender waits about
2-3 s after opening before writing (`ears`: 3 s, `sim`: 2.2 s, `--push`: 2.0 s).

---

## 4. Data flow and state

### 4.1 Board state (`tasklot_full_v2`)

| State | Shape | Notes |
|---|---|---|
| Car registry | up to 8 UIDs (`known[8][10]`, `knownLen[8]`, `carCount`) | Append-only until reset. Shared by all six readers. |
| Labels | `taskOf[8][19]` | 18 characters + NUL. |
| Occupancy | `occupant[4]` (car index or -1), `lastSeen[4]` | One car per space; one space per car. |
| Lane debounce | `lastLaneCar[2]`, `lastLaneAt[2]` | `LANE_COOLDOWN_MS = 2000`. |
| Interaction | `ordering` (car or -1), `playing` (car or -1) | At most one order and one read-back. |
| Screen | `overlay` (`NONE`, `ORDERING`, `PLAYING`, `ANNOUNCE`), flash timers, `lotBuf[4][21]`, `shown[4][21]` | `paintScreen()` is the only code that draws. |
| Full text | `fullText[121]`, `wrapLine[9][21]`, page index | Filled by `FULL*`. |
| Persistence | EEPROM, magic `0x7A`, version 1, 243 bytes | Only with `#define REMEMBER 1` (ships 0). |

Main loop order, every ~60 ms: read commands -> poll spaces 1-4 (arrival if empty,
presence ping if occupied) -> poll speaker lane -> poll pickup lane -> `delay(60)` ->
tick the screen. Lanes are polled after spaces so a car carried out of a space is marked
gone before a lane sees it.

**Presence.** `HaltA` puts a tag to sleep, and a sleeping tag ignores
`PICC_IsNewCardPresent`. So an occupied space is pinged with `PICC_WakeupA` (which a
halted tag answers) and halted again. A space is reported empty only after
`GONE_MS = 1200` ms with no answer, so one missed ping is not a departure.
`#define USE_PRESENCE 0` turns departures off entirely (arrivals still work).

**Screen overlays.** All timed screen effects are state plus a timestamp, ticked by
`loop()`. Nothing uses `delay()` for the screen, because a blocking flash would let the
64-byte RX buffer overflow. Serial output is never delayed; only the glass waits.

| Overlay | Shown when | Ends when |
|---|---|---|
| `ORDER IN PROGRESS` (flashes every 500 ms) | A blank car passes the speaker | Any car parks, or the ordering car is collected |
| `ORDER IS IN` (flashes every 220 ms) | A car parks while an order is open | 1.6 s later |
| `ALL DONE!!` (flashes every 220 ms) | A labelled car is collected, or `DONE` on a labelled car | 1.6 s later |
| `YOUR ORDER` (paged) | A labelled car passes the speaker, `PLAY`, or `FULLSHOW` | 12 s, any car parks, `LOT`, or the car is collected |

### 4.2 Laptop state (`tasklot_ears.py`)

| State | Meaning |
|---|---|
| `tasks[car]` | Full cleaned transcript the daemon itself produced. Lost on restart. |
| `labels[car]` | The label the board is showing, learned from `TASK` echoes and from what was sent. |
| `rec`, `rec_car`, `rec_t0` | The live ffmpeg process, which car it is for, when it started. |
| `jobs` | Queue of `(car, wav_path)` for the transcription worker thread. |

Threads: the main thread reads serial lines and dispatches; a worker thread transcribes and
labels (transcription takes seconds and the read loop must keep draining the port); a
recording capper closes any order still open after `MAX_REC = 60` s; two file watchers
poll `/tmp/tasklot_say.txt` (text to speak with `say`) and `/tmp/tasklot_cmd.txt` (a
board command to send; `RESET` clears the laptop's memory and sends `CLEAR`).

### 4.3 The label pipeline

```
WAV --whisper-cli--> raw transcript
    --clean_transcript()--> drop [BLANK_AUDIO]/(music), split on ">>" and sentence ends,
                            drop filler-only segments, strip leading greetings, de-duplicate
    --condense()--> {full, lcd, due, raw}
    --> send "CAR n <lcd>" immediately
    --llm_label()--> optional better label, only if it passes every guard
    --> send "CAR n <better>" if it differs
```

`condense()` stages, each running only while the text is still too long (width 18):
disfluency removal (looped), due-hint extraction (`by Friday`, `at 4pm`, `tonight` ...),
intent-prefix removal (`I need to`, `remind me to` ...), first sentence only, then for the
LCD: cut at a reason clause (`about`, `because`, `whether` ...), drop trailing
prepositional phrases (never below two words), abbreviate (`professor` -> `Prof`,
`and` -> `&` ...), drop articles, remove up to 3 interior vowels from the longest word,
and finally truncate at a word boundary if that keeps at least 55 % of the width. No
ellipsis: the HD44780 has no glyph for it and it would cost 3 characters.

`condense.js` is canonical and runs in node and the browser; the Python `Condenser`
(`tasklot/condenser.py`, with `condense.py` kept as its command-line front door) mirrors it.
Both are checked against `tools/voice/cases.json`. The simulator carries an inlined copy
of `condense.js` between `BEGIN`/`END` markers, regenerated by `sync_page.py`.

LLM label guards (`tasklot_ears.py`): skipped when the cleaned transcript has fewer than
3 content words; output is collapsed to one line, stripped of quotes and a trailing
period, ASCII-filtered, and trimmed word-by-word to 18 characters; rejected if it shares
no word (or 3-letter prefix) with the transcript (`unrelated`), or if it contains a
time/date word or digit that the transcript does not (`invented`). Any exception or
timeout (`TASKLOT_LLM_TIMEOUT`, default 25 s) falls back to the rule-based label.

---

## 5. Edge cases and failure modes

Each row says what happens **today** and what the refactor should guarantee. "Keep"
means the current behaviour is correct and needs a test pinning it. "Fix" means current
behaviour is a known gap; the refactor should change it and test the new behaviour.
"Manual" means it can only be checked on hardware (see section 7).

### Recording and transcription

| # | Case | Today | Target |
|---|---|---|---|
| E-01 | Silent or near-empty recording | `transcribe()` returns `""` if the WAV is missing or under 8000 bytes; worker logs "nothing transcribed" and sends nothing. The car keeps showing `CAR n`. | Keep. Test with a fake transcriber returning `""`. |
| E-02 | Transcript is only filler (`"Hello?"`, `"Um. Okay."`, `[BLANK_AUDIO]`) | `clean_transcript()` returns empty or punctuation only; worker sends nothing. | Keep. Unit-test `clean_transcript` on these inputs. |
| E-03 | Car parked within 0.6 s of ordering | `stop_recording_proc()` sleeps until `MIN_HOLD` has passed, because stopping ffmpeg during device init can produce no file at all. | Keep, with the hold injectable so tests do not sleep. |
| E-04 | ffmpeg will not stop gracefully | `q` on stdin, then SIGINT, then SIGKILL (logs that the WAV may be truncated). | Keep the escalation; test with a fake process. |
| E-05 | ffmpeg missing or fails to start | Logged; `rec` stays `None`. On park, the old `/tmp/tasklot_order_car<n>.wav` from a **previous** order (if any) is transcribed and becomes this car's task. | Fix: delete or uniquely name the WAV per order; a failed start must lead to "nothing recorded", never a stale file. |
| E-06 | `whisper-cli` or the model missing | `subprocess` raises, caught, returns `""`, logs `[whisper] failed`. | Keep, but check for the binary and model at startup and log once, clearly. |
| E-07 | Whisper hangs | 90 s timeout, then `""`. | Keep; timeout as a named constant. |
| E-08 | Car never parked after ordering | Capper stops recording after 60 s and transcribes it for that car. | Keep. Test with an injected clock. |
| E-09 | Same car re-read at the speaker while recording | Firmware debounces for 2 s; ears also ignores a second `SPEAKER` for the car already recording. | Keep both. |
| E-10 | A second, different car passes the speaker while the first is recording | Firmware replaces the order (`ordering` = new car). Ears stops the first ffmpeg **without transcribing it**; the first car's speech is discarded silently. | Decide and test. Minimum: log that car A's order was abandoned. |
| E-11 | Car B parks while car A is ordering | Firmware closes the order (any park closes it) and flashes `ORDER IS IN`. Ears only stops recording when the **ordering** car parks, so the mic stays open for car A until A parks or the 60 s cap. Screen and laptop disagree. | Fix: the laptop should close the order on any `parked` event, matching the firmware, and assign the recording to car A. Pin with a test. |
| E-12 | Ordering car carried straight to the pickup lane | Firmware clears the order and the label. Ears drops `tasks`/`labels` for the car but **keeps recording**; at the 60 s cap it transcribes and sends `CAR n <label>` to a car that was just collected. | Fix: a `collected` event for the recording car stops and discards the recording. |
| E-13 | Car collected while its label is being computed (the ~8 s LLM window) | The LLM upgrade still sends `CAR n <label>`, re-labelling a car that is now blank. | Fix: the worker checks the car is still awaiting a label (generation counter or order id) before each send. |
| E-14 | Car lifted off the speaker and never parked or collected | Same as E-08. | Keep. |

### Text, width, and character set

| # | Case | Today | Target |
|---|---|---|---|
| E-15 | Transcript longer than the LCD width | `condense()` shrinks to <= 18 characters through the stages in 4.3; firmware also truncates `CAR` text to 18. | Keep. Property test: for every fixture and random inputs, `len(lcd) <= 18`. |
| E-16 | Very long full text for read-back | Ears chunks at <= 40 characters on word boundaries; firmware keeps 120 characters and 9 wrapped rows (3 pages). Text past that is silently dropped. | Keep, and test that the chunker never emits a `FULL` line over 47 characters. A single word over 40 characters currently produces one oversized chunk; split it. |
| E-17 | Non-ASCII in the transcript (smart quotes, accents, emoji, other scripts) | `ascii_only()` maps smart quotes and dashes to ASCII and drops every other non-ASCII character (`cafe` keeps, `café` becomes `caf`). A fully non-ASCII transcript becomes empty and is skipped. `send()` also drops non-ASCII. The firmware stores whatever bytes arrive, so a non-ASCII byte from another sender shows as a garbage glyph. | Keep the filter; decide whether to transliterate accents (`é` -> `e`) rather than drop them. Test both condensers on the same non-ASCII cases. |
| E-18 | Empty or whitespace-only input to `condense()` | Returns all-empty fields. | Keep (already in `cases.json`). |
| E-19 | Label exactly 18 characters, or 19 | 18 passes untouched; 19 goes through devowel (`Print reader coupn`). | Keep (in `cases.json`). |
| E-20 | `CAR <n>` with no text, or `DONE <n>` | Both blank the label; `DONE` also closes any order/read-back and may flash `ALL DONE!!`. | Keep. |
| E-21 | LLM returns a hallucinated label (adds a deadline, a day, a number, or an unrelated phrase) | Rejected by `invented()` / `unrelated()`; the rule-based label stays. | Keep. Unit-test both guards with the real failures recorded in the code comments (`PAPER DUE TONIGHT`, `FRI`, `PLACE ORDER`). |
| E-22 | LLM times out, is missing, or returns empty or multi-line output | Timeout/exception -> `None`; output is collapsed to one line and trimmed to 18. | Keep, with the LLM runner injectable so tests never call a real model. |
| E-23 | Too little was said for the LLM | Under 3 content words: LLM skipped. | Keep. |

### Lot, cars, and readers

| # | Case | Today | Target |
|---|---|---|---|
| E-24 | All four spaces full | There is no fifth space; a fifth car simply has nowhere to park. All four lines show tasks. The 3.3 V rail is most stressed in this state (flaky reads). | Keep. Manual: check reads stay reliable with every space and both lanes populated. |
| E-25 | More than 8 distinct cars | The ninth UID prints `no car slots left` and is ignored until reset. | Keep; the limit as a named constant shared by firmware and laptop (`MAX_CARS = 8`). |
| E-26 | Car moved directly from space 1 to space 2 | Arrival on 2 releases space 1 immediately (`SPACE 1 -> CAR n left`, then `SPACE 2 <- CAR n parked`); the list reorders, the task is not duplicated. | Keep. Host-side test of `ParkingLot`. |
| E-27 | Two cars swapped between spaces | Slow swap (both cars off their spaces for more than 1.2 s): each lift reports `left`, each set-down reports `parked`, and the final state is the swapped order. Fast swap (both set down within 1.2 s): the presence ping does not check which tag answers, so neither space ever reads empty or sees an arrival, and the board keeps the old assignment, with each label on the other car's line. (This row first said the arrival rule in E-26 catches the fast swap; it does not. See quirk 5 in [`firmware/README.md`](firmware/README.md).) | Keep the slow swap; the fast swap stays a known gap, because fixing it changes the bench-verified reader call sequence. Host-side tests with a fake clock cover both timings. |
| E-28 | A car is lifted and replaced on the same space quickly (under 1.2 s) | No event; presence ping missed fewer than `GONE_MS`. | Keep. |
| E-29 | Partial RFID read (UID with a trailing run of zero bytes, or three or more zero bytes) | Rejected by `plausibleUID()`; not registered as a new car. (A "seen twice" rule was tried and reverted because a resting tag is never re-polled.) | Keep. Host-side test with the two bench UIDs `04 D1 60 00 00 00 00` and `04 E1 63 00 00 00 00`. |
| E-30 | Simulator drives a v2 board | The simulator sends `PARK`, `LEAVE`, `EMPTY` after connecting; v2 replies `* unknown command:` to each. Labels (`CAR`) and `ORDER`/`PLAY`/`DONE` work. | Decide: either v2 accepts `PARK`/`LEAVE`/`EMPTY` (useful when a reader is dead), or the simulator stops sending them to v2. Document whichever. |
| E-31 | Commands sent faster than the board can print | Commands merge in the 64-byte RX buffer. Ears paces 0.35 s; the CLI `--push` paces only 0.08 s and can overrun. | Fix the CLI to use the same paced `SerialLink`. Test that `SerialLink` never writes two lines inside the pacing window. |
| E-32 | Unknown, partial, or garbled line from the board (`3>Charge baCAR 4 Glu`, empty line) | Ears ignores lines it cannot parse; the read loop never dies. | Keep (covered by `test_ears_mock.py` scenario 5). Parser unit tests for every event in 3.1 and for garbage. |
| E-33 | A board line contains a substring that looks like an event | Ears uses unanchored `re.search`. A label is at most 18 characters, and `CAR 9 reading back` is exactly 18, so the echo `TASK 3 CAR 9 reading back` (or the lot line `1>CAR 9 reading back`) would trigger a read-back for car 9. | Fix: anchor event patterns to the start of the line. |
| E-34 | Bad car number in a command (`CAR 0`, `CAR 9`, `ORDER abc`) | `* bad car number: <n>`; no state change. | Keep. |

### Serial link and process lifecycle

| # | Case | Today | Target |
|---|---|---|---|
| E-35 | Serial port missing at startup | `serial.Serial()` raises and the daemon exits with a traceback. | Fix: clear error naming `TASKLOT_PORT`, non-zero exit. |
| E-36 | USB unplugged while running | `readline()` raises; ears logs, sleeps 1 s, and retries `readline()` on the dead handle forever. Writes fail and are logged. | Fix: `SerialLink` detects the disconnect, closes, and reopens with backoff; logs the state change once. |
| E-37 | Board resets (port reopened, USB brownout) | The board forgets every car and label (unless `REMEMBER 1`). The simulator re-sends every label after connecting; ears does not, so its `tasks`/`labels` no longer match the board. | Fix: after (re)connecting, ears waits for the boot banner and re-sends known labels. Note car numbers are assigned in the order tags are first seen, so after a reset the same physical car can get a different number; persistence (`REMEMBER 1`) is the real fix for that. |
| E-38 | Daemon restarted while the board keeps running | Ears has no full text; it learns labels from `TASK` echoes as they arrive. A read-back for a car it has no text for logs "nothing to show". | Keep; consider asking the board for state (`LOT`) on connect. |
| E-39 | Another program holds the port (Serial Monitor, the simulator) | Open fails. | Same as E-35, with a hint that only one program can hold the port. |
| E-40 | No LCD connected | Firmware logs once and runs; the lot still prints to serial. | Keep. |
| E-41 | A reader not talking at boot (`0x00`/`0xFF`) | Reported in the boot banner; the sketch still runs. | Keep. Manual check. |
| E-42 | `millis()` wraps (about 49.7 days) | Timers use unsigned subtraction or a signed difference, so they survive the wrap. | Keep; host-side test the timer helpers across the wrap. |
| E-43 | `/tmp/tasklot_*` files written by another user or left over | Watchers blank the files at startup; anything written is spoken or sent to the board. | Keep the behaviour, but put the paths in one config place. |

---

## 6. Target architecture

The goal is to move from module-level globals and long procedural functions to small
objects around the real state, with every external tool behind an interface that tests
can replace. Behaviour should not change except where section 5 says "Fix".

### 6.1 Python: `tools/voice/tasklot/`

```
tools/voice/
  tasklot/
    __init__.py
    config.py        Settings dataclass built from environment variables (port, baud, model,
                     LLM on/off and timeout, MAX_REC, MIN_HOLD, pacing, /tmp paths)
    task.py          Task (dataclass)
    lot.py           Lot
    protocol.py      BoardEvent types + parse_line(); command formatters
    serial_link.py   SerialLink
    recorder.py      Recorder
    transcriber.py   Transcriber (whisper.cpp), FakeTranscriber
    cleaner.py       TranscriptCleaner (clean_transcript, strip_lead, FILLER)
    condenser.py     Condenser (port of condense.js; same cases.json)
    labeler.py       Labeler (LLM label + guards)
    ears.py          Ears orchestrator
    cli.py           thin CLI: `python3 -m tasklot ears`, `python3 -m tasklot add --text ...`
  tests/
    test_condenser.py, test_cleaner.py, test_labeler.py, test_protocol.py,
    test_lot.py, test_serial_link.py, test_recorder.py, test_ears.py, test_ears_mock.py
  condense.js        stays canonical for the browser; mirrors Condenser
  cases.json         shared fixtures
```

| Class | Owns | Key methods | Collaborators / test seam |
|---|---|---|---|
| `Task` (dataclass) | `car: int`, `full: str`, `lcd: str`, `due: str`, `raw: str`, `source: str`, `recorded: datetime \| None` | `to_dict()`, `from_dict()` | none |
| `Lot` | Per-car tasks and the label the board is showing; which car (if any) is recording; an order id per car so stale results can be dropped (E-12, E-13) | `begin_order(car)`, `close_order()`, `set_label(car, text)`, `collect(car)`, `full_text(car)`, `is_current(car, order_id)` | pure, no I/O |
| `BoardEvent` + `parse_line()` | One frozen dataclass per event in 3.1 (`Ordering`, `Parked`, `Left`, `Playback`, `Collected`, `TaskEcho`, `NewCar`, `Pong`, `Unknown`) | `parse_line(str) -> BoardEvent`, anchored patterns (E-33) | pure |
| `SerialLink` | The port, the write lock, the pacing, reconnect with backoff | `open()`, `readline()`, `send(cmd)`, `close()` | takes a `serial_factory`, so tests pass a fake port or a pty |
| `Recorder` | The ffmpeg process, start time, per-order WAV path | `start(car) -> Path`, `stop() -> Path \| None`, `elapsed()` | takes a `process_factory` and a clock |
| `Transcriber` | whisper-cli path, model path, timeout | `transcribe(path) -> str` | `FakeTranscriber(text)` replaces `TASKLOT_FAKE_TRANSCRIPT` |
| `TranscriptCleaner` | Filler and greeting rules | `clean(text) -> str` | pure |
| `Condenser` | Width and the rule tables | `condense(text) -> Task fields`, `lot_lines(lot)`, `first_step(text)`, `playback(task)` | pure; must pass `cases.json` exactly like `condense.js` |
| `Labeler` | Prompt, guards (`unrelated`, `invented`, `fit`), timeout | `label(text) -> str \| None` | takes a `runner(prompt) -> str` so tests never call a model |
| `Ears` | Wires everything: reads events, drives `Recorder`, queues work, sends commands | `handle(event)`, `run()`, `work_once()` | all collaborators injected; `handle()` is synchronous and testable without threads |
| CLI | argument parsing only | `main(argv)` | none |

`tasklot_voice.py`'s offline path (audio file or text -> `tasks.json` -> push) becomes a
CLI subcommand that reuses `Condenser`, `Transcriber`, `Task`, and `SerialLink`, so it
gets the same pacing (E-31).

### 6.2 Firmware: `firmware/tasklot_full_v2/`

Arduino builds every `.h`/`.cpp` in the sketch folder, so the split needs no build
tooling. Hardware-free classes should compile on the laptop too, so their logic can be
unit-tested with the system C++ compiler and a fake reader.

```
firmware/tasklot_full_v2/
  tasklot_full_v2.ino   setup() + loop(): construct objects, wire them, tick them
  config.h              pins, MAX_CARS, TASK_LEN, GONE_MS, LANE_COOLDOWN_MS, timings, feature flags
  RfidSlot.h/.cpp       one RC522: arrival read, presence ping, UID plausibility, version report
  CarRegistry.h/.cpp    UID -> car index, labels, optional EEPROM persistence
  ParkingLot.h/.cpp     four spaces + two lanes: occupancy, order/read-back state, lane debounce
  LcdView.h/.cpp        overlays, flashing, paging, row diffing; the only code that draws
  SerialProtocol.h/.cpp line buffer, command parsing, event printing (exact strings in 3.1)
firmware/tests/          host-side tests (fake RfidSlot, fake clock), built with c++
```

| Class | Owns | Notes |
|---|---|---|
| `RfidSlot` | An `MFRC522`, its SS pin, role (space or lane) | `pollArrival(Uid&)`, `stillPresent()`, `versionByte()`. Keeps the bench-verified call sequence exactly: `IsNewCardPresent` -> `ReadCardSerial` -> `HaltA` -> `StopCrypto1`, and `WakeupA` -> `HaltA` for presence. |
| `CarRegistry` | `known`, `knownLen`, `carCount`, `taskOf`, EEPROM layout | `find(uid)`, `add(uid)`, `label(car)`, `setLabel(car, text)`, `clearAll()`, `save()`/`load()`/`forget()`. `isPlausible(uid)` can live here or in `RfidSlot`. |
| `ParkingLot` | `occupant`, `lastSeen`, `ordering`, `playing`, lane debounce | Methods return what happened (`Arrived`, `Left`, `Ordering`, `Playback`, `Collected`) instead of printing, so the `.ino` passes results to `SerialProtocol` and `LcdView`. This is what makes E-26 to E-29 host-testable. |
| `LcdView` | `LiquidCrystal_I2C`, `shown`, `lotBuf`, overlay state, wrap buffer | `showLot(lines)`, `showOrdering(car)`, `announce(msg)`, `showFullText(text)`, `tick(now)`. Must stay non-blocking. |
| `SerialProtocol` | Command buffer | `poll()` returns parsed commands; `print*()` emits the event strings in section 3.1 byte for byte. Any change to those strings breaks the laptop and the simulator. |

Constraints for the firmware refactor: keep the wire format identical (or change both
sides in the same commit with tests), keep `delay(60)` and the poll order, keep the boot
deselect of all six SS pins before `SPI.begin()`, keep SRAM use low (strings in `F()`),
and keep `REMEMBER` and `USE_PRESENCE` as compile-time switches.

### 6.3 `condense.js`

`condense.js` mirrors `Condenser`: same stages, same tables, same outputs on
`cases.json`. It keeps the UMD wrapper so it loads in node (`require`) and the browser
(`window.TaskLotCondense`). After any change, run `python3 tools/voice/sync_page.py` to
re-inline it into the simulator.

### 6.4 Voice pipeline: as built

The Python side follows 6.1, plus four small modules: `logs.py` (the one logging
helper), `side_channels.py` (`FileInbox` for the say/command files, `Speaker` for macOS
`say`), `offline.py` (`OfflineTool`, the logic behind the `voice` command), and
`tests/fakes.py` (fake clock, port, and ffmpeg process). `condense.js` exposes a
`Condenser` class alongside the function API the simulator calls.

Wire strings are unchanged: the end-to-end test asserts every byte the daemon writes
for a scripted session, captured from the code at import. Behaviour changed only where
section 5 says "Fix", plus three small corrections found while porting:

| Item | Now |
|---|---|
| E-05 | One WAV per order (`tasklot_order_car<n>_<order>.wav`); a leftover file is deleted before recording and a failed start records nothing. WAVs are deleted after transcription. |
| E-06 | Missing `whisper-cli` or model is logged once at startup. |
| E-10 | Car A's recording is discarded, as before, and the abandonment is logged. |
| E-11 | Any `parked` event closes the open order; the recording belongs to the ordering car. |
| E-12, E-13 | Pickup during an order discards the recording; per-car order ids drop stale labels and LLM upgrades. |
| E-16 | Words over 40 characters are split; no empty `FULL ` line is sent. |
| E-31 | `--push` uses the paced `SerialLink`. |
| E-33 | Event patterns are anchored at the start of the line. |
| E-35, E-39 | An unopenable port prints what to check and exits with status 2. |
| E-36, E-37 | `SerialLink` reopens with backoff; `Ears` re-sends known labels after a reconnect. |
| E-17 | Unchanged: accents are dropped, not transliterated (still open). |
| `TASK <n> ` | The empty echo after `DONE` is now parsed; it clears the label and the laptop's full text. |
| Python port | Two places where `condense.py` had drifted from `condense.js` (a sentence break at index 0; a due phrase that also appears inside an earlier word) now match `condense.js`. Found by the cross-language test. |

### 6.5 Firmware: as built

The firmware follows 6.2, with smaller pieces split out of the planned `ParkingLot`
and `LcdView`: `LaneDebouncer` (lane debounce), `ReadbackText` (the full-text buffer
and word wrap), and the `OrderState` struct (who is ordering or being read back), which
`TaskLot` owns and `LcdView` reads. A `Uid` value type carries reads, and `TaskLot`
coordinates everything. The wire format
is unchanged byte for byte; the host tests in `firmware/tests/` pin it against
transcripts recorded from the original sketch. The full write-up, including the one
deliberate behaviour change and a corrected reading of E-27 (a fast swap is not caught
by the arrival rule), is in [`firmware/README.md`](firmware/README.md).

---

## 7. Manual test checklist (hardware)

These cannot be automated. Run them with `firmware/tasklot_full_v2` flashed and
`tasklot_ears.py` attached.

1. Boot banner shows six readers answering (`ok - genuine` or `ok - clone`) and `LCD: 0x27` or `0x3F`.
2. Tap each car on space 1: each new car prints `* NEW CAR registered`.
3. Blank car past the speaker: `ORDER IN PROGRESS` flashes; ears logs `[mic] recording`.
4. Speak a task, park the car: `ORDER IS IN` flashes, then the lot shows `CAR n`, then the label within about a second.
5. Move the car to another space: the list reorders with no announcement.
6. Labelled car past the speaker: `YOUR ORDER` with the full text, paging if long, back to the lot within 12 s.
7. Car through the pickup lane: `ALL DONE!!`, the space empties, the label is gone.
8. Fill all four spaces and pass a car over each lane: reads stay reliable (3.3 V rail check).
9. Unplug and replug USB with ears running: note what ears does (E-36, E-37).
10. Lift a car for under a second and put it back: no `left` event (E-28).

---

## 8. Running the automated checks

```bash
make test        # voice pipeline (python3 -m unittest + node --test; the ears end-to-end test
                 # needs pyserial) and the firmware host tests (firmware/tests/run_tests.sh)
make firmware    # compile every sketch for the Mega 2560 (needs arduino-cli + MFRC522 + LiquidCrystal I2C)
```

Baseline at import (before any refactor): `node test_condense.js` 11/11 cases,
`python3 test_condense.py` 11/11 cases plus the simulator copy check, and
`test_ears_mock.py` 6/6 checks with pyserial 3.5 and `TASKLOT_LLM=0`. All eight sketches
compile for the Mega 2560 (v2 uses 5 % of flash). `build/cad/audit.py` reports no blockers
and 3 warnings (two parts need a large-bed printer; the car dimensions are unmeasured).

---

## 9. Open questions

1. **Lane pin assignment.** The original v2 header comment said speaker SS 36 and pickup
   SS 37; the code defines speaker 37 and pickup 36 (`PIN_SS_SPEAKER`, `PIN_SS_PICKUP` in
   `config.h`); `build/wiring/gen_plan.py` labels SS 36 "RECORD" and SS 37
   "DRIVE-THROUGH". The code is what ran on the bench and the mock test's boot banner
   matches it (speaker 37), so the firmware comments now follow the code. The wiring plan
   should be made to agree once that is confirmed against the physical deck.
2. **Does `PLAY` need a timeout?** `FULLSHOW` and a speaker read-back expire after 12 s;
   `PLAY` does not.
3. **E-30:** should v2 accept `PARK`/`LEAVE`/`EMPTY` from the simulator?
4. **E-10:** what should happen to car A's speech when car B takes over the speaker?
