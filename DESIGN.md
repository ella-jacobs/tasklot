# TaskLot — design

How TaskLot works: the interaction, the exact serial protocol between the board and the
laptop, the state each side keeps, the edge cases and failure modes the system handles,
and the architecture of the code in this repo. The edge-case list (section 5) is the test
spec: each case is pinned by an automated test, or its row says why it cannot be.

The code began as one Arduino sketch and a few procedural Python scripts and was then
refactored into the classes in section 6, keeping the serial protocol byte for byte.
[Appendix A](#appendix-a-history-before-the-refactor) records what changed: how each
fixed edge case behaved before, and the test baseline at import.

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
  Laptop: the tasklot package in tools/voice (tasklot_ears.py starts the Ears daemon)
            |
            +-- Recorder: ffmpeg records the mic to a 16 kHz mono WAV
            +-- Transcriber: whisper.cpp `whisper-cli` (local transcription)
            +-- TranscriptCleaner -> Condenser (rule-based, 18-char label)
            +-- Labeler: optional `claude -p` label upgrade, with hallucination guards

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

## 3. Serial protocol

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
| `SPACE <s>  <- CAR <n> parked` | A car arrives on space `s`. | ears (closes any open order, updates occupancy), sim |
| `SPACE <s>  -> CAR <n> left` | A space goes quiet for `GONE_MS`, or the car arrived somewhere else, or it was collected. | ears (updates occupancy), sim |
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
| `SerialLink` (the ears daemon and `tasklot_voice.py --push`) | One line per `send()`, under a lock, at least `SEND_PACING_S` (0.35 s) apart. Non-ASCII is dropped on the way out. |
| `tasklot-sim.html` | A queue; the next line goes only after the board's reply ends (two rule lines, or `PONG`), or after 1.2 s. |

Opening the serial port toggles DTR and **resets the Mega**. Every sender waits after
opening before writing: `SerialLink` 3 s (`TASKLOT_RESET_DELAY`), the simulator 2.2 s.

---

## 4. Data flow and state

### 4.1 Board state (`tasklot_full_v2`)

| State | Owner | Notes |
|---|---|---|
| Car registry | `CarRegistry`: up to `MAX_CARS` (8) UIDs, in the order first seen | Append-only until reset. Shared by all six readers. |
| Labels | `CarRegistry`: one label per car, `TASK_LEN` (18) characters + NUL | |
| Occupancy | `ParkingLot`: the car on each space and when it last answered | One car per space; one space per car. |
| Lane debounce | `LaneDebouncer`, one per lane | `LANE_COOLDOWN_MS = 2000`. |
| Interaction | `OrderState` (owned by `TaskLot`): `ordering` and `playing` | At most one order and one read-back. |
| Screen | `LcdView`: the overlay (`NONE`, `ORDERING`, `PLAYING`, `ANNOUNCE`), flash timers, the rendered lot and the rows on the glass | `LcdView` is the only code that draws. |
| Full text | `ReadbackText`: up to 120 characters, word-wrapped into up to 9 rows of 20 | Filled by `FULL*`. |
| Persistence | EEPROM, magic `0x7A`, version 1, 243 bytes | Only with `REMEMBER 1` in `config.h` (ships 0). |

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

### 4.2 Laptop state (the Ears daemon)

| State | Owner | Meaning |
|---|---|---|
| Tasks | `Lot.tasks` | car -> `Task`: the full cleaned transcript the daemon produced. Lost on restart. |
| Labels | `Lot.labels` | The label the board is showing, learned from `TASK` echoes and from what was sent. |
| Spaces | `Lot.spaces` | Which car is on each space, from `parked` / `left` events; logged after every change. |
| Open order | `Lot.recording`, `Recorder` | Which car is being recorded; the ffmpeg process and when it started. |
| Order ids | `Lot` | One per car, bumped by every new order and every pickup; a result started under an older id is dropped (E-12, E-13). |
| Jobs | `Ears.jobs` | Queue of `Job(car, order_id, path)` for the transcription worker. |

Threads: the main thread reads serial lines and dispatches them (stopping ffmpeg and
sending a read-back's paced lines happen there too); a worker thread transcribes and
labels, because transcription takes seconds and the read loop must keep draining the
port; a capper closes any order still open after `MAX_RECORDING_S` (60 s); an inbox
thread polls the say file (text to speak with `say`) and the command file (a board
command to send; `RESET` clears the laptop's memory and sends `CLEAR`). Both files live
in the per-user temp directory by default (E-43).

### 4.3 The label pipeline

```
WAV --Transcriber (whisper-cli)--> raw transcript
    --TranscriptCleaner.clean()--> drop [BLANK_AUDIO]/(music), split on ">>" and sentence
                                   ends, drop filler-only segments, strip leading
                                   greetings, de-duplicate
    --Condenser.condense()--> {full, lcd, due, raw}
    --> send "CAR n <lcd>" immediately
    --Labeler.label()--> optional better label, only if it passes every guard
    --> send "CAR n <better>" if it differs
```

`Condenser.condense()` stages, each running only while the text is still too long (width 18):
disfluency removal (looped), due-hint extraction (`by Friday`, `at 4pm`, `tonight` ...),
intent-prefix removal (`I need to`, `remind me to` ...), first sentence only, then for the
LCD: cut at a reason clause (`about`, `because`, `whether` ...), drop trailing
prepositional phrases (never below two words), abbreviate (`professor` -> `Prof`,
`and` -> `&` ...), drop articles, remove up to 3 interior vowels from the longest word,
and finally truncate at a word boundary if that keeps at least 55 % of the width. No
ellipsis: the HD44780 has no glyph for it and it would cost 3 characters.

`condense.js` is the reference version and runs in node and the browser; the Python
`Condenser` (`tasklot/condenser.py`, with `condense.py` as its command-line front door)
mirrors it rule for rule, and a cross-language test feeds both the same inputs.
Both are checked against `tools/voice/cases.json`. The simulator carries an inlined copy
of `condense.js` between `BEGIN`/`END` markers, regenerated by `sync_page.py`.

LLM label guards (`Labeler`): skipped when the cleaned transcript has fewer than
3 content words; output is collapsed to one line, stripped of quotes and a trailing
period, ASCII-filtered, and trimmed word-by-word to 18 characters; rejected if it shares
no word (or 3-letter prefix) with the transcript (`unrelated`), or if it contains a
time/date word or digit that the transcript does not (`invented`). Any exception,
timeout (`TASKLOT_LLM_TIMEOUT`, default 25 s) or non-zero exit falls back to the
rule-based label. The `claude` CLI runs with no tools and without saving the session.

---

## 5. Edge cases and failure modes

Each row says what the code does now, and its status:

- **Tested**: pinned by an automated test (Python, node, or the firmware host tests).
- **Fixed**: the original code had a gap here; the refactor changed it, and a test pins
  the new behaviour. [Appendix A](#appendix-a-history-before-the-refactor) has the old
  behaviour.
- **Manual**: can only be checked on hardware (the item number in section 7).
- **Open** or **known gap**: an undecided question (section 9), or a limitation kept on
  purpose.

### Recording and transcription

| # | Case | Now | Status |
|---|---|---|---|
| E-01 | Silent or near-empty recording | `Transcriber.transcribe()` returns `""` when the WAV is missing or under 8000 bytes; `Ears` logs "nothing transcribed" and sends nothing, so the car keeps showing `CAR n`. | Tested |
| E-02 | Transcript is only filler (`"Hello?"`, `"Um. Okay."`, `[BLANK_AUDIO]`) | `TranscriptCleaner` leaves nothing but punctuation, and `Ears` sends nothing, because an empty label would blank the row. | Tested |
| E-03 | Car parked within 0.6 s of ordering | `Recorder.stop()` first waits until `MIN_HOLD_S` (0.6 s) has passed, because stopping ffmpeg during device start-up can leave no file at all. The clock and sleep are injected, so tests do not wait. | Tested |
| E-04 | ffmpeg will not stop gracefully | `q` on stdin, then SIGINT, then SIGKILL, which logs that the WAV may be truncated. | Tested |
| E-05 | ffmpeg missing or fails to start | Each order gets its own WAV (`tasklot_order_car<n>_<order>.wav`). A leftover file with that name is deleted before recording, and a failed start records nothing, so a previous order's audio can never become this car's task. WAVs are deleted once transcribed, and on shutdown. | Fixed |
| E-06 | `whisper-cli` or the model missing | Checked once at startup and logged clearly. A run that raises or exits non-zero logs why (exit code and stderr) and yields `""`. | Fixed |
| E-07 | Whisper hangs | `WHISPER_TIMEOUT_S` (90 s), then `""`. | Tested |
| E-08 | Car never parked after ordering | The capper closes the order after `MAX_RECORDING_S` (60 s) and transcribes it for that car. | Tested |
| E-09 | Same car re-read at the speaker while recording | The firmware's `LaneDebouncer` ignores repeats for 2 s, and `Ears` ignores a second `SPEAKER` for the car already recording instead of restarting. | Tested |
| E-10 | A second, different car passes the speaker while the first is recording | The firmware replaces the order. `Ears` discards car A's recording and logs that it was abandoned. | Tested; open (9.4) |
| E-11 | Car B parks while car A is ordering | Any `parked` event closes the open order, as the firmware does, and the recording belongs to car A. | Fixed |
| E-12 | Ordering car carried straight to the pickup lane | The `collected` event stops and discards the recording; nothing is transcribed for a car that is now blank. | Fixed |
| E-13 | Car collected while its label is being computed (the ~8 s LLM window) | Every result carries the order id it was started under, and `Lot` bumps the id on each new order and each pickup, so a stale label or LLM upgrade is dropped and logged. | Fixed |
| E-14 | Car lifted off the speaker and never parked or collected | Same as E-08. | Tested |

### Text, width, and character set

| # | Case | Now | Status |
|---|---|---|---|
| E-15 | Transcript longer than the LCD width | `Condenser.condense()` shrinks it to at most 18 characters through the stages in 4.3; the firmware also truncates `CAR` text to 18. A property test checks the width on every fixture and on seeded random memos, in both languages. | Tested |
| E-16 | Very long full text for read-back | The read-back is sent in chunks of at most 40 characters on word boundaries; a single word over 40 is split, and no empty `FULL ` line is sent. The firmware keeps 120 characters (9 wrapped rows, 3 pages); text past that is dropped. | Fixed |
| E-17 | Non-ASCII in the transcript (smart quotes, accents, emoji, other scripts) | `ascii_only()` maps smart quotes and dashes to ASCII and drops every other non-ASCII character (`cafe` stays, `café` becomes `caf`: accents are dropped, not transliterated). A fully non-ASCII transcript becomes empty and is skipped, and `SerialLink` drops non-ASCII on the way out. Both condensers are tested on the same cases. | Tested |
| E-18 | Empty or whitespace-only input to `condense()` | All fields empty. | Tested (`cases.json`) |
| E-19 | Label exactly 18 characters, or 19 | 18 passes untouched; 19 goes through devowel (`Print reader coupn`). | Tested (`cases.json`) |
| E-20 | `CAR <n>` with no text, or `DONE <n>` | Both blank the label; `DONE` also closes any order or read-back, and flashes `ALL DONE!!` only if the car had a label. The laptop reads the empty echo `TASK <n> ` and forgets the car's text. | Tested |
| E-21 | LLM returns a hallucinated label (adds a deadline, a day, a number, or an unrelated phrase) | Rejected by `invented()` / `unrelated()`; the rule-based label stays. The tests use the real failures recorded in the code (`PAPER DUE TONIGHT`, `ESSAY FRI`, `PLACE ORDER`). | Tested |
| E-22 | LLM times out, is missing, exits non-zero, or returns empty or multi-line output | Any exception, timeout or non-zero exit falls back to the rule-based label; output is collapsed to one line and trimmed to 18. The runner is injected, so no test calls a model. | Tested |
| E-23 | Too little was said for the LLM | Under 3 content words, the LLM is not asked. | Tested |

### Lot, cars, and readers

| # | Case | Now | Status |
|---|---|---|---|
| E-24 | All four spaces full | There is no fifth space; all four lines show tasks. The 3.3 V rail is most stressed in this state. | Tested; rail: manual (7.8) |
| E-25 | More than 8 distinct cars | The ninth UID prints `no car slots left` and is ignored until reset. `MAX_CARS = 8` in both `config.h` and `config.py`. | Tested |
| E-26 | Car moved directly from space 1 to space 2 | Arrival on 2 releases space 1 at once (`SPACE 1 -> CAR n left`, then `SPACE 2 <- CAR n parked`); the list reorders and the task is not duplicated. | Tested |
| E-27 | Two cars swapped between spaces | Slow swap (both cars off their spaces for more than 1.2 s): each lift reports `left`, each set-down reports `parked`, and the lot ends up swapped. Fast swap (both set down within 1.2 s): the presence ping does not check which tag answers, so the board keeps the old assignment, with each label on the other car's line (quirk 5 in [`firmware/README.md`](firmware/README.md)). Fixing it would change the bench-verified reader call sequence. | Slow: tested. Fast: known gap |
| E-28 | A car is lifted and replaced on the same space quickly (under 1.2 s) | No event: one missed presence ping is not a departure; `GONE_MS` (1.2 s) of silence is. | Tested; manual (7.10) |
| E-29 | Partial RFID read (UID with a trailing run of zero bytes, or three or more zero bytes) | `Uid::isPlausible()` rejects it, so it is never registered as a new car. Tested with the two bench UIDs `04 D1 60 00 00 00 00` and `04 E1 63 00 00 00 00`. (A "seen twice" rule was tried and reverted, because a resting tag is never re-polled.) | Tested |
| E-30 | Simulator drives a v2 board | The simulator sends `PARK`, `LEAVE`, `EMPTY` after connecting; v2 replies `* unknown command:` to each. Labels (`CAR`) and `ORDER`/`PLAY`/`DONE` work. | Open (9.3) |
| E-31 | Commands sent faster than the board can print | Every laptop sender, including `tasklot_voice.py --push`, goes through `SerialLink`, which never writes two lines less than 0.35 s apart. | Fixed |
| E-32 | Unknown, partial, or garbled line from the board (`3>Charge baCAR 4 Glu`, empty line) | Parsed as unknown and ignored; one bad line never stops the read loop. | Tested |
| E-33 | A board line contains a substring that looks like an event | Event patterns are anchored at the start of the line, so the echo `TASK 3 CAR 9 reading back` or the lot line `1>CAR 9 reading back` triggers nothing. | Fixed |
| E-34 | Bad car number in a command (`CAR 0`, `CAR 9`, `ORDER abc`) | `* bad car number: <n>`; no state change. | Tested |

### Serial link and process lifecycle

| # | Case | Now | Status |
|---|---|---|---|
| E-35 | Serial port missing at startup | A message naming the port and `TASKLOT_PORT`, and exit status 2; no traceback. | Fixed |
| E-36 | USB unplugged while running | `SerialLink` notices the dead handle, closes it, logs once, and reopens with backoff (1, 2, 4, then every 8 s). | Fixed; manual (7.9) |
| E-37 | Board resets (port reopened, USB brownout) | After a reopen, `Ears` re-sends every label it knows and drops an order that was being recorded, since the board has forgotten it. Car numbers are assigned in the order tags are first seen, so after a reset a physical car can get a different number; `REMEMBER 1` (EEPROM) is the real fix. | Fixed; manual (7.9) |
| E-38 | Daemon restarted while the board keeps running | The laptop has no full text; it learns labels from `TASK` echoes, and a read-back falls back to the label. A read-back for a car it knows nothing about logs "nothing to show". | Tested |
| E-39 | Another program holds the port (Serial Monitor, the simulator) | Same as E-35, with a hint that only one program can hold the port. | Fixed |
| E-40 | No LCD connected | The firmware logs once and runs; the lot still prints to serial. | Tested |
| E-41 | A reader not talking at boot (`0x00`/`0xFF`) | Reported in the boot banner; the sketch still runs. | Tested; manual (7.1) |
| E-42 | `millis()` wraps (about 49.7 days) | `elapsedMs()` and `deadlineReached()` in `timing.h` use unsigned and signed differences, so timers survive the wrap. | Tested |
| E-43 | Side-channel files (say, command) written by someone else, or left over | The files live in the per-user temp directory by default (`$TMPDIR` on macOS, private to the account), and every path is in `config.py`. The watchers blank them at startup without following a symlink; anything written afterwards is spoken or sent to the board. | Fixed |

---

## 6. Architecture

Small objects around the real state, with every external tool (the serial port, ffmpeg,
whisper.cpp, the LLM, `say`, the clock) behind a seam a test can replace. The wire format
is unchanged from the original code byte for byte: the ears end-to-end test asserts every
byte the daemon writes for a scripted session, and the firmware host tests diff every
serial byte and LCD frame against transcripts recorded from the original sketch.

### 6.1 Voice pipeline: `tools/voice/tasklot/`

```
tools/voice/
  tasklot/
    config.py         Settings from environment variables; every default in one place
    logs.py           the one logging helper
    task.py           Task (dataclass)
    lot.py            Lot: tasks, labels, spaces, the open order, per-car order ids
    protocol.py       board events + parse_line() (anchored patterns); command formatters
    serial_link.py    SerialLink: paced writes, reconnect with backoff
    recorder.py       Recorder (ffmpeg), NullRecorder
    transcriber.py    Transcriber (whisper.cpp), ScriptTranscriber (offline CLI), FakeTranscriber
    cleaner.py        TranscriptCleaner
    condenser.py      Condenser (mirrors condense.js; same cases.json)
    labeler.py        Labeler: optional LLM label behind guards
    side_channels.py  FileInbox (the say and command files), SayVoice (macOS `say`)
    ears.py           Ears: the live daemon
    offline.py        OfflineTool: the `voice` command (audio or text -> tasks.json -> board)
    cli.py            argument parsing and wiring only: `python3 -m tasklot ears|voice`
  tasklot_ears.py, tasklot_voice.py   the original commands, now thin entry points into cli.py
  condense.js         the reference condenser, for node and the browser
  condense.py         command-line front door to Condenser
  cases.json          shared fixtures for both condensers
  sync_page.py        re-inlines condense.js into the simulator
  tests/              one test file per module, fakes.py, and the end-to-end test
```

| Class | Owns | Key methods | Test seam |
|---|---|---|---|
| `Task` (dataclass) | `car`, `full`, `lcd`, `due`, `raw`, `source`, `recorded` | `to_dict()`, `from_dict()`, `from_condensed()` | none needed |
| `Lot` | Per-car tasks and the label the board shows; which car is on each space; which car is recording; an order id per car so stale results can be dropped (E-12, E-13) | `begin_order(car)`, `close_order()`, `set_label()`, `park()`, `leave()`, `collect(car)`, `rows()`, `is_current(car, order_id)` | pure, no I/O except `tasks.json` load/save |
| Board events + `parse_line()` | One frozen dataclass per event in 3.1 (`Ordering`, `Parked`, `Left`, `Playback`, `Collected`, `TaskEcho`, `NewCar`, `Pong`, `Unknown`) | `parse_line(str)`, `car_command()`, `full_text_commands()` | pure |
| `SerialLink` | The port, the write lock, the pacing, reconnect with backoff | `open()`, `readline()`, `send(cmd)`, `close()` | takes a `serial_factory`, so tests pass a fake port or a pty |
| `Recorder` | The ffmpeg process, its start time, the per-order WAV path | `start(car, order_id)`, `stop()`, `discard()`, `elapsed()` | takes a `process_factory`, a clock and a sleep |
| `Transcriber` | whisper-cli path, model path, timeout | `problems()`, `transcribe(path)` | takes a `runner`; `FakeTranscriber(text)` backs `TASKLOT_FAKE_TRANSCRIPT` |
| `TranscriptCleaner` | Filler and greeting rules | `clean(text)`, `is_empty(text)` | pure |
| `Condenser` | Width and the rule tables | `condense(text)`, `lot_lines(rows)`, `first_step(text)`, `playback(task)` | pure; must pass `cases.json` exactly like `condense.js` |
| `Labeler` | Prompt, guards (`unrelated`, `invented`, `fit`), timeout | `label(text) -> str \| None` | takes a `runner(prompt, timeout)`, so tests never call a model |
| `FileInbox`, `SayVoice` | One watched file; the `say` voice and rate | `reset()`, `poll()`; `pick_voice()`, `speak(text)` | real temp files; `SayVoice` takes `run` and `popen` |
| `Ears` | Wires everything: reads events, drives the `Recorder`, queues work, sends commands | `handle_line()`, `work_once()`, `check_cap()`, `on_reconnect()`, `shutdown()` | every collaborator injected; `handle()` and `work_once()` are synchronous, so tests need no threads |
| `OfflineTool` | `tasks.json` and the offline flow | `add()`, `add_audio()`, `preview()`, `push()`, `watch()` | injected transcriber, `link_factory` and `sleep` |
| CLI | argument parsing only | `main(argv)` | none needed |

Behaviour changed only where section 5 says Fixed, plus these, each with a test:

- The empty echo `TASK <n> ` after `DONE` is parsed: it clears the label and the
  laptop's full text.
- Two places where `condense.py` had drifted from `condense.js` (a sentence break at
  index 0, and a due phrase that also appears inside an earlier word) now match
  `condense.js`. The cross-language test found them.
- Quitting with Ctrl-C or SIGTERM deletes the open recording and any WAV still queued.
- `Ears` logs the laptop's view of the lot (`[lot] 1>... | 2>...`) after every park
  and leave, so it can be checked against the board's printout.
- The LLM runs through `claude -p` with no tools and without saving the session.

### 6.2 Firmware: `firmware/tasklot_full_v2/`

Arduino builds every `.h`/`.cpp` in the sketch folder, so the split needs no build
tooling. The hardware-free classes also compile on a laptop, so their logic is
unit-tested there with the system C++ compiler against fakes of the Arduino libraries.

```
firmware/tasklot_full_v2/
  tasklot_full_v2.ino   builds the objects; setup() and loop() are a few lines each
  config.h              pins, MAX_CARS, TASK_LEN, GONE_MS, LANE_COOLDOWN_MS, timings, switches
  timing.h              millis() arithmetic that survives the 32-bit wrap
  TaskLot.h/.cpp        the coordinator: what each read and each command does; owns OrderState
  RfidSlot.h/.cpp       one RC522: arrival read, presence ping, version check
  Uid.h/.cpp            a tag UID and the plausibility filter
  CarRegistry.h/.cpp    UID -> car -> label, optional EEPROM persistence
  ParkingLot.h/.cpp     which car is on each space, the presence timeout, lot lines
  LaneDebouncer.h/.cpp  one event per sweep on a lane
  ReadbackText.h/.cpp   the FULL text buffer and its word wrap
  LcdView.h/.cpp        overlays, flashing, paging, row diffing; the only code that draws
  SerialProtocol.h/.cpp line buffer, command parsing, every event string in 3.1
firmware/tests/         host tests: fake Arduino libraries, unit tests, golden transcripts
```

`LaneDebouncer`, `ReadbackText` and the `OrderState` struct (who is ordering or being
read back) are split out of what would otherwise be `ParkingLot` and `LcdView`, and `LcdView` reads `OrderState` instead of keeping its own
copy, so the screen and the interaction cannot disagree. The class-by-class table, the
memory use before and after, the one deliberate behaviour change, and the original's
quirks (kept or fixed) are in [`firmware/README.md`](firmware/README.md).

Constraints the split kept: the wire format is identical, `delay(60)` and the poll
order are unchanged, all six SS pins are still deselected before `SPI.begin()`, SRAM
use stays low (printed strings in `F()`), and `REMEMBER` and `USE_PRESENCE` are still
compile-time switches.

### 6.3 `condense.js`

`condense.js` is the reference version of the condenser rules, and `Condenser` mirrors
it: same stages, same tables, same outputs on `cases.json`. It keeps the UMD wrapper so
it loads in node (`require`) and the browser (`window.TaskLotCondense`). After any change,
run `python3 tools/voice/sync_page.py` to re-inline it into the simulator; a test fails
if the inlined copy is stale.

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
9. Unplug and replug USB with ears running: ears logs `lost the board`, reconnects once the board is back, and re-sends every label (E-36, E-37).
10. Lift a car for under a second and put it back: no `left` event (E-28).

---

## 8. Running the automated checks

```bash
make test        # firmware host tests, Python unittest, node --test
make test PYTHON=.venv/bin/python   # the same, with pyserial, so the ears end-to-end test runs
make firmware    # compile every sketch for the Mega 2560 (needs arduino-cli + MFRC522 + LiquidCrystal I2C)
```

No test calls an LLM or needs a microphone, a whisper model, or a board. The README's
"How it was tested" section lists what each suite covers.

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

---

## Appendix A. History: before the refactor

"The original code" in this document is what was imported: the single-file sketch
`firmware/tasklot_full_v2/tasklot_full_v2.ino` and the scripts `tools/voice/tasklot_ears.py`,
`tools/voice/condense.{js,py}` and `tools/voice/tasklot_voice.py`, with
`tools/sim/tasklot-sim.html`. The refactor replaced the sketch's globals with the classes
in 6.2 and the scripts with the `tasklot` package in 6.1 (the two scripts are now thin
entry points with the same flags). The originals are in the git history.

### A.1 Edge cases that changed

How each case that section 5 marks Fixed (and E-10, where only a log line was added)
behaved in the original code. Paths and names are the original ones.

| # | Case | Before the refactor |
|---|---|---|
| E-05 | ffmpeg missing or fails to start | Logged; `rec` stays `None`. On park, the old `/tmp/tasklot_order_car<n>.wav` from a **previous** order (if any) is transcribed and becomes this car's task. |
| E-06 | `whisper-cli` or the model missing | `subprocess` raises, caught, returns `""`, logs `[whisper] failed`. |
| E-10 | A second, different car passes the speaker while the first is recording | Firmware replaces the order (`ordering` = new car). Ears stops the first ffmpeg **without transcribing it**; the first car's speech is discarded silently. |
| E-11 | Car B parks while car A is ordering | Firmware closes the order (any park closes it) and flashes `ORDER IS IN`. Ears only stops recording when the **ordering** car parks, so the mic stays open for car A until A parks or the 60 s cap. Screen and laptop disagree. |
| E-12 | Ordering car carried straight to the pickup lane | Firmware clears the order and the label. Ears drops `tasks`/`labels` for the car but **keeps recording**; at the 60 s cap it transcribes and sends `CAR n <label>` to a car that was just collected. |
| E-13 | Car collected while its label is being computed (the ~8 s LLM window) | The LLM upgrade still sends `CAR n <label>`, re-labelling a car that is now blank. |
| E-16 | Very long full text for read-back | Ears chunks at <= 40 characters on word boundaries; firmware keeps 120 characters and 9 wrapped rows (3 pages). Text past that is silently dropped. |
| E-31 | Commands sent faster than the board can print | Commands merge in the 64-byte RX buffer. Ears paces 0.35 s; the CLI `--push` paces only 0.08 s and can overrun. |
| E-33 | A board line contains a substring that looks like an event | Ears uses unanchored `re.search`. A label is at most 18 characters, and `CAR 9 reading back` is exactly 18, so the echo `TASK 3 CAR 9 reading back` (or the lot line `1>CAR 9 reading back`) would trigger a read-back for car 9. |
| E-35 | Serial port missing at startup | `serial.Serial()` raises and the daemon exits with a traceback. |
| E-36 | USB unplugged while running | `readline()` raises; ears logs, sleeps 1 s, and retries `readline()` on the dead handle forever. Writes fail and are logged. |
| E-37 | Board resets (port reopened, USB brownout) | The board forgets every car and label (unless `REMEMBER 1`). The simulator re-sends every label after connecting; ears does not, so its `tasks`/`labels` no longer match the board. |
| E-39 | Another program holds the port (Serial Monitor, the simulator) | Open fails. |
| E-43 | `/tmp/tasklot_*` files written by another user or left over | Watchers blank the files at startup; anything written is spoken or sent to the board. |

### A.2 Test baseline at import

The imported code came with three root-level test scripts: `node test_condense.js` passed
11/11 cases, `python3 test_condense.py` 11/11 cases plus the simulator copy check, and
`test_ears_mock.py` 6/6 checks with pyserial 3.5 and `TASKLOT_LLM=0`. All eight sketches
compiled for the Mega 2560 (v2 used 5 % of flash), and `build/cad/audit.py` reported no
blockers and 3 warnings (two parts need a large-bed printer; the car dimensions are
unmeasured). The three scripts were replaced by the suites in `tools/voice/tests/`
(`unittest` and `node --test`), which pin the same behaviour; `test_ears_mock.py` there
is the same end-to-end check rewritten as a `unittest` case.
