# TaskLot firmware

The Arduino Mega 2560 sketch that runs the physical lot: six RC522 RFID readers (four
parking spaces, a speaker lane, a pickup lane), a 20 x 4 character LCD, and a line-based
serial protocol to the laptop. The board never handles audio; it maps sticker UIDs to car
numbers, car numbers to 18-character labels, and shows the lot.

> **Status: the object-oriented refactor compiles and passes the host tests; it has not
> yet been re-tested on hardware.** Flash it and run the
> [manual hardware test checklist](#manual-hardware-test-checklist) before relying on it.
> The last bench-tested version is the monolithic sketch in the git history (commit
> "Import firmware: v2 board sketch and the sketches that led to it").

This file describes how the sketch is built, how it behaves (recorded before the refactor,
so the refactor could be checked against it), how it is tested, and the hardware checks
that cannot be automated. The protocol and the system-wide edge cases are specified in
[`../DESIGN.md`](../DESIGN.md) (sections 3 and 5); this file is the firmware-side view.

| Path | What |
|---|---|
| `tasklot_full_v2/` | The current sketch, split into classes (see Architecture). |
| `tests/` | Host-side tests: fake Arduino libraries, unit tests, scripted scenarios, golden transcripts. |
| `history/` | The earlier sketches that built up to v2 (see its README). |

## Build and flash

| | |
|---|---|
| Board | Elegoo Mega 2560 (ATmega2560) |
| FQBN | `arduino:avr:mega:cpu=atmega2560` (core `arduino:avr` 1.8.8) |
| Libraries | `MFRC522` 1.4.12 (miguelbalboa/rfid), `LiquidCrystal I2C` 1.1.2 (Frank de Brabander) |

```bash
arduino-cli core install arduino:avr@1.8.8
arduino-cli lib install "MFRC522@1.4.12" "LiquidCrystal I2C@1.1.2"
arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 firmware/tasklot_full_v2
arduino-cli upload  --fqbn arduino:avr:mega:cpu=atmega2560 -p <port> firmware/tasklot_full_v2
```

Serial monitor: 9600 baud. Only one program can hold the port, so close the monitor
before running the laptop daemon or the simulator.

The two feature switches (below) are `#define`s in `config.h`. They can also be set from
the command line without editing the file, for example:

```bash
arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 \
  --build-property "compiler.cpp.extra_flags=-DREMEMBER=1" firmware/tasklot_full_v2
```

## Architecture

Arduino compiles every `.h` / `.cpp` in the sketch folder together with the `.ino`, so the
split needs no build setup. All objects are globals of fixed size, built in
`tasklot_full_v2.ino`; nothing is allocated at run time.

```
RfidSlot x6 --UIDs--> TaskLot --labels------> CarRegistry  (EEPROM if REMEMBER)
                        |  \---occupancy---> ParkingLot
                        |  \---lane passes-> LaneDebouncer x2
                        |  \---events------> SerialProtocol --USB--> laptop
                        \-----screens-----> LcdView ----I2C--> LCD
                                               ^ reads OrderState, ReadbackText, CarRegistry
```

| File | Class / role | Hardware? |
|---|---|---|
| `tasklot_full_v2.ino` | Builds the objects; `setup()` and `loop()` (five lines: commands, spaces, lanes, `delay(60)`, screen tick). | - |
| `config.h` | Every pin, size, timing constant and feature switch. | - |
| `timing.h` | `elapsedMs()` / `deadlineReached()`: `millis()` arithmetic that survives the 32-bit wrap. | no |
| `TaskLot` | The coordinator: what each read and each command does (the state machine below). Owns `OrderState`. | via the others |
| `RfidSlot` | One RC522. `readArrival()` and `isStillPresent()` keep the bench-verified MFRC522 call sequences exactly; `classifyReaderVersion()` for the boot check. | MFRC522 |
| `Uid` | A tag UID; `isPlausible()` rejects partial reads. | no |
| `CarRegistry` | UID -> car index -> label, and the EEPROM layout. | EEPROM (REMEMBER 1) |
| `ParkingLot` | Which car is on each space; presence timeout; renders a lot line. | no |
| `LaneDebouncer` | One event per sweep on a lane. | no |
| `ReadbackText` | Collects `FULL` chunks and word-wraps them into LCD rows. | no |
| `LcdView` | The only code that draws: lot, overlays, flashing, paging, row diffing. Non-blocking. | LiquidCrystal_I2C |
| `SerialProtocol` | Reads command lines, parses them into `Command` values, prints every event string. | Serial |

Why this shape: the classes follow the state that really exists on the board (the car
registry, the four spaces, the lane debounce, the screen, the serial line), and the logic
that decides things (`ParkingLot`, `LaneDebouncer`, `ReadbackText`, `CarRegistry`,
`SerialProtocol::parse`) has no hardware calls, so it builds and is tested on a laptop.
`TaskLot` is the one place where reads turn into events, so the order of serial lines is
easy to check against the original. `LcdView` reads `OrderState` instead of keeping its
own copy, so the screen and the interaction can never disagree about which car is
ordering or being read back.

## Pin map

| Device | Pins | Notes |
|---|---|---|
| All six RC522 readers | 3.3V, GND, RST -> A0 (shared), SCK -> 52, MOSI -> 51, MISO -> 50, IRQ unconnected | **3.3 V only; 5 V kills the reader.** Shared RST means resetting one resets all. |
| Space 1 / 2 / 3 / 4 reader | SS -> 44 / 45 / 40 / 41 | Space 1 is the top line of the lot. |
| Speaker lane reader | SS -> 37 | As defined in the code (see the note below). |
| Pickup lane reader | SS -> 36 | As defined in the code. |
| LCD2004A + I2C backpack | VCC -> 5V, GND, SDA -> 20, SCL -> 21 | Address 0x27 or 0x3F, found by scanning at boot. |
| Pin 53 | unwired | `SPI.begin()` drives it as the hardware SS. |

Lane pins: the original sketch header said speaker 36 / pickup 37, but the code (which is
what ran on the bench) defines speaker 37 / pickup 36. This README follows the code. See
open question 9.1 in `DESIGN.md`.

Power: the Mega's 3.3 V rail is rated 50 mA and six RC522s draw 78-156 mA. Four readers
were bench-tested on the internal rail; six may need an external 3.3 V regulator. The
symptom of a starved rail is good version bytes at boot (SPI needs almost no current) but
no tag reads (the RF field does).

## Behaviour of the sketch (recorded before the refactor)

Everything in this section describes the monolithic `tasklot_full_v2.ino` as imported. The
refactor keeps all of it, byte for byte on the serial line; the one deliberate change is
quirk 2 in the table at the end of this section (a screen-only fix).

### Compile-time switches

| Switch | Default | Effect |
|---|---|---|
| `REMEMBER` | `0` | `1` mirrors the car list and labels into EEPROM (243 bytes: magic `0x7A`, version 1, car count, then 8 x {UID length, 10 UID bytes, 19 label bytes}) and restores them at boot. Writes use `EEPROM.update()` so unchanged bytes are not rewritten. |
| `USE_PRESENCE` | `1` | `0` turns off departure detection for the four spaces (every space is polled for arrivals only). Lanes are arrival-only either way. |

### Timing and size constants

| Constant | Value | Why |
|---|---|---|
| Loop delay | 60 ms | Lets the shared SPI bus settle between reader polls. |
| `GONE_MS` | 1200 ms | A space is empty only after this long with no answer to a presence ping, so one missed ping is not a departure. |
| `LANE_COOLDOWN_MS` | 2000 ms | The same car re-read on a lane inside this window is the same pass. The window slides while the car lingers. A different car always counts. |
| `FLASH_SLOW_MS` | 500 ms | Flash period of `ORDER IN PROGRESS`. |
| `FLASH_FAST_MS` | 220 ms | Flash period of `ORDER IS IN` and `ALL DONE!!`. |
| `ANNOUNCE_MS` | 1600 ms | How long an announcement covers the lot. |
| `PAGE_MS` | 2500 ms | Page time of the `YOUR ORDER` read-back when it has more than 3 rows. |
| `PLAY_MS` | 12000 ms | A read-back started by the speaker or `FULLSHOW` falls back to the lot after this. `PLAY` has no timeout. |
| `MAX_CARS` | 8 | Distinct UIDs remembered until reset. |
| `TASK_LEN` | 18 | Label length: the lot line is `n>` plus 18 characters on a 20-column LCD. |
| Command buffer | 48 bytes | Lines longer than 47 characters are truncated, not rejected. |
| `FULL_LEN` | 120 | Read-back text buffer; more is dropped. |
| `WRAP_LINES` | 9 | Read-back rows (3 pages of 3). |

### Main loop

Every pass, in this order:

1. Drain serial input and run every complete command.
2. Poll spaces 1 to 4. An empty space is polled for an arrival
   (`PICC_IsNewCardPresent` -> `PICC_ReadCardSerial` -> `PICC_HaltA` -> `PCD_StopCrypto1`).
   An occupied space is pinged with `PICC_WakeupA` and halted again; `STATUS_OK` or
   `STATUS_COLLISION` counts as present.
3. Poll the speaker lane, then the pickup lane (arrival sequence only, plus the lane
   cooldown). Lanes go after spaces so a car carried out of a space is marked gone before
   a lane sees it.
4. `delay(60)`.
5. Tick the screen (flash phase, announcement expiry, read-back paging and timeout).

The screen is never driven with `delay()`: a blocking flash would let the 64-byte serial
receive buffer overflow and merge commands.

### State

| State | Meaning |
|---|---|
| Car registry | Up to 8 UIDs, in the order first seen; car number = position + 1. Append-only until reset. |
| Labels | One 18-character label per car. |
| Occupancy | Which car is on each space (or none) and when it last answered. A car holds at most one space. |
| `ordering` | The car whose order is open, or none. |
| `playing` | The car being read back, or none. |
| Overlay | `NONE` (the lot), `ORDERING`, `PLAYING`, or `ANNOUNCE`. Only the screen painter draws. |
| Read-back text | Up to 120 characters from `FULL`, word-wrapped into up to 9 rows of 20. |

### State machine (what each input does)

| Input | Effect |
|---|---|
| New UID on any reader | If plausible and a car slot is free, registers it and prints `* NEW CAR registered`. If the UID is implausible, prints `* ignored a bad read`, then (a quirk, see below) `no car slots left`. If all 8 slots are used, prints `no car slots left`. Either failure ignores the read. |
| Car arrives on space *s* | Closes any order and any read-back. If it was on another space, that space prints `left` first. Prints `parked` and the lot. If an order was open, the screen flashes `ORDER IS IN`; otherwise the overlay is dropped and the lot shows. |
| Occupied space silent for `GONE_MS` | Prints `left` and the lot. |
| Blank car passes the speaker | Prints `SPEAKER  CAR n ordering`, opens the order, shows `ORDER IN PROGRESS` (flashing), prints the lot. A second car replaces the first. |
| Labelled car passes the speaker | Prints `PLAYBACK CAR n reading back`, closes any order, clears the read-back text, shows `YOUR ORDER` with the 18-character label until `FULLSHOW` arrives, prints the lot. Times out after `PLAY_MS`. |
| Car passes the pickup lane | Prints `PICKUP   CAR n collected`, blanks its label (`TASK n `), releases its space (`left`), closes the order or read-back if it is this car's, drops the overlay, prints the lot, and flashes `ALL DONE!!` if the car had a label. |
| `ANNOUNCE` timer expires | Back to the lot. |
| `PLAYING` timer expires | Read-back closed, back to the lot. |

### Serial messages

Board to laptop (each line ends `\r\n`; the spacing is part of the format):

```
* NEW CAR registered -> CAR <n>   UID <hex> <hex> ... <hex> 
SPACE <s>  <- CAR <n> parked
SPACE <s>  -> CAR <n> left
SPEAKER  CAR <n> ordering
PLAYBACK CAR <n> reading back
PICKUP   CAR <n> collected
TASK <n> <label>
PONG
--------------------
<s>><label | - | CAR n>        (four lines between two rules)
* tasks cleared
* bad car number: <n>
* unknown command: <line>
  no car slots left - reset the board to clear
* ignored a bad read (truncated UID): <hex> ... 
* EEPROM forgotten - reset the board to start clean      (REMEMBER 1)
* REMEMBER is off - nothing is saved                     (REMEMBER 0)
EEPROM: nothing saved yet | EEPROM: bad count, ignoring | EEPROM: restored <k> car(s) and their tasks
```

UID bytes are two-digit uppercase hex, each followed by a space. The boot banner is the
title line, one `space <k> reader (SS <pin>): 0x<ver>   <verdict>` line per space, the
`speaker` and `pickup ` lines, the rail hint, the LCD line, the optional `EEPROM:` line,
three help lines, a blank line, and a lot printout. Version verdicts: `0x91`/`0x92` genuine,
`0x88`/`0x12` clone, `0x00`/`0xFF` not talking, anything else unexpected but answering.

Laptop to board (matched by prefix in this order, so `LOTS` acts as `LOT`): `PING`, `LOT`,
`FORGET`, `ORDER <n>`, `PLAY <n>`, `FULLCLR`, `FULLSHOW <n>`, `FULL <chunk>`, `CLEAR`,
`DONE <n>`, `CAR <n> <text>`. Car numbers are 1-based and must be 1..8; anything else
(including a non-number, which reads as 0) prints `* bad car number:`. The effect of each
command is in `DESIGN.md` section 3.2.

### Memory use, before and after the refactor

Compiled with arduino-cli, core `arduino:avr` 1.8.8, MFRC522 1.4.12, LiquidCrystal I2C
1.1.2, for the Mega 2560 (253952 bytes of flash, 8192 bytes of SRAM):

| Build | Flash before | Flash after | Static RAM before | Static RAM after |
|---|---|---|---|---|
| Default (`REMEMBER 0`, `USE_PRESENCE 1`) | 15084 | 16024 (+940, 6 %) | 1565 | 1561 (19 %) |
| `REMEMBER 1` | 15874 | 16850 (+976, 6 %) | 1565 | 1561 |
| `USE_PRESENCE 0` | 14758 | 15762 (+1004, 6 %) | 1549 | 1561 |

The extra flash is the cost of passing objects by reference and of the event methods
that used to be inlined `Serial.print` runs; it is under 0.4 % of the Mega's flash. Static
RAM is the same within a few bytes: the classes hold exactly the arrays the globals held,
and all serial strings stay in flash (`F()`) as before. (With `USE_PRESENCE 0` the
original let the compiler drop the unused presence timestamps; the refactor keeps them in
`ParkingLot`, 12 bytes more.)

### Known quirks in the original, and what the refactor did with each

Recorded so each one is kept or fixed deliberately. "Kept" means the refactor reproduces
it byte for byte (the golden transcripts pin it); changing it is a one-line decision for
later.

| # | Quirk | Refactor |
|---|---|---|
| 1 | An implausible UID prints `* ignored a bad read (truncated UID): ...`, a blank line, then `  no car slots left - reset the board to clear`, because every failed registration was reported as "slots full". The laptop parses neither line. | Kept (`TaskLot::identify`). |
| 2 | `DONE <n>` cleared the order and the read-back but left their screens up when the car had no label: the LCD kept flashing `ORDER IN PROGRESS` with `CAR 0`, or a read-back with no text read the label of car index -1 (out of bounds). | **Fixed** in its own commit: DONE now closes those screens. Serial output is unchanged. |
| 3 | The header comment said there is no read-back step (the code has one) and had the lane pins swapped relative to the code. | Fixed (comments only). |
| 4 | `confirmedTwice()` and its buffer were dead code. | Removed. |
| 5 | **A fast swap is invisible.** Presence pings (`WakeupA`) do not check which tag answered, so if two cars swap spaces and both land within `GONE_MS` (1.2 s), the board keeps the old assignment and the lot shows the labels on the wrong lines. A slow swap (lift both, wait, set down) works. `DESIGN.md` E-27 first assumed the arrival rule catches the fast swap; it does not, and E-27 now says so. | Kept. A fix would re-read the UID on a presence ping, which changes the bench-verified call sequence, so it needs hardware testing first. |
| 6 | Collecting a different car while one is ordering drops the `ORDER IN PROGRESS` screen, but the order stays open (the laptop keeps recording); `ORDER IS IN` still flashes when the ordering car parks. | Kept. |
| 7 | `PLAY <n>` does not set a timeout but keeps any earlier one: after a speaker read-back or `FULLSHOW` that was ended early by `LOT`, a later `PLAY` ends at the old deadline (or on the next loop, if that deadline has passed). | Kept. Related to `DESIGN.md` open question 9.2. |

## Tests

```bash
firmware/tests/run_tests.sh                                            # host tests, needs only a C++17 compiler
arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 firmware/tasklot_full_v2   # compile check for the board
make -C firmware check                                                 # both, plus the REMEMBER / USE_PRESENCE builds
```

`run_tests.sh` builds the sketch sources with the system compiler against small fakes of
the Arduino core, SPI, Wire, EEPROM, MFRC522 and LiquidCrystal_I2C (`tests/fakes/`). The
fake RC522 models the tag states the firmware relies on: a tag answers `REQA` until it is
halted, a halted tag answers only `WUPA`, and taking it out of the field resets it.

1. **Unit tests** (`tests/unit_tests.cpp`, 175 checks) exercise each class directly: partial
   UID reads (E-29), the ninth car (E-25), moves and presence timeouts (E-26, E-28), lane
   debounce (E-09), read-back wrap limits (E-16), command parsing and bad car numbers
   (E-34), exact event strings, the LCD overlays and paging, a missing LCD (E-40), and
   every timer across the `millis()` wrap (E-42).
2. **Scenarios** (`tests/scenarios.cpp`) run the whole sketch (`setup()` and `loop()`)
   through 14 scripted sessions (boot, degraded boot, park and leave, move and swap,
   ordering, read-back, pickup, every command, a full registry, `USE_PRESENCE 0`, and
   three `REMEMBER 1` power cycles), and record every serial byte and the LCD after each
   step. The transcripts in `tests/golden/` were recorded from the monolithic sketch
   before the refactor; the refactor reproduces all 14 byte for byte, except the one
   deliberate change (quirk 2), which is its own commit with its own golden diff.

To re-record the golden files after an intended behaviour change, run
`firmware/tests/run_tests.sh --regen firmware/tasklot_full_v2` (needs `arduino-cli`) and
review the diff.

What the host tests cannot show: real RF behaviour (read range, collisions, the starved
3.3 V rail), I2C timing, and serial pacing on a real 64-byte buffer. That is what the
checklist below is for.

## Manual hardware test checklist

Run with the sketch flashed, the Serial Monitor (or the laptop daemon) attached at 9600
baud, and the LCD connected. Each line is a pass/fail check. The `E-` numbers refer to
`DESIGN.md` section 5.

**Boot**
- [ ] Banner lists all six readers with `ok - genuine` or `ok - clone`, and `LCD: 0x27` or `LCD: 0x3F`. (E-41)
- [ ] Unplug one reader's SS wire and reboot: that reader shows `<-- NOT TALKING`, the rest of the banner and the lot still appear.
- [ ] Unplug the LCD and reboot: `LCD: none found` is printed, readers still work and the lot prints to serial. (E-40)

**Car placed**
- [ ] Put a never-seen car on space 1: `* NEW CAR registered -> CAR 1   UID ...`, then `SPACE 1  <- CAR 1 parked`, then the lot with `1>CAR 1`.
- [ ] The LCD shows the same four lines as the serial printout.

**Car removed**
- [ ] Lift the car off space 1 and hold it away: about 1.2 s later `SPACE 1  -> CAR 1 left`, and the lot shows `1>-`.
- [ ] Lift a car and put it back on the same space within about one second: no `left` or `parked` line. (E-28)

**Car moved and swapped**
- [ ] Move a car from space 1 straight to space 2: `SPACE 1  -> CAR n left` then `SPACE 2  <- CAR n parked`; the label appears once, on line 2. (E-26)
- [ ] Swap the cars on spaces 1 and 2 slowly (lift both, wait two seconds, set them down swapped): final lot shows them swapped, each label once. (E-27)
- [ ] Swap them quickly (both down within a second): expect the lot NOT to change (quirk 5). Note what you see.

**Ordering (speaker lane)**
- [ ] Pass a blank car over the speaker: `SPEAKER  CAR n ordering`; the LCD flashes `ORDER IN PROGRESS` about twice a second with `CAR n`, `listening...`, `park it when done`.
- [ ] Hold the same car over the speaker for several seconds: only one `ordering` line. (E-09)
- [ ] Park the car: `parked`, then `ORDER IS IN` flashes fast for about 1.6 s, then the lot.
- [ ] Send `CAR n Email the Prof` from the monitor: `TASK n Email the Prof`, and the lot line updates.
- [ ] Move a labelled car to another space: the lot reorders with no `ORDER IS IN`.

**Read-back**
- [ ] Pass a labelled car over the speaker: `PLAYBACK CAR n reading back`, LCD shows `YOUR ORDER` and the label, back to the lot within 12 s.
- [ ] With the laptop daemon attached, a long task pages through 3 rows at a time every 2.5 s.
- [ ] Park any car during a read-back: the read-back ends and the lot shows.

**Pickup lane**
- [ ] Pass a labelled, parked car through the pickup lane: `PICKUP   CAR n collected`, `TASK n `, `SPACE s  -> CAR n left`, `ALL DONE!!` flashes, then the lot with the space empty.
- [ ] Pass a blank car through the pickup lane: same lines, but no `ALL DONE!!`.
- [ ] Order with a blank car, then carry it straight to the pickup lane: `ORDER IN PROGRESS` stops. (E-12, board side)
- [ ] Order with a blank car, then send `DONE n` for it from the monitor: the screen goes back to the lot (quirk 2 fix; it used to stay on `ORDER IN PROGRESS` with `CAR 0`).

**All slots full**
- [ ] Put a car on each of the four spaces and pass a fifth over each lane: every read still registers; no missed `parked` lines over a few minutes. (E-24, 3.3 V rail)
- [ ] Introduce a ninth distinct sticker: `  no car slots left - reset the board to clear`, nothing else changes. (E-25)

**Reader failure and bad reads**
- [ ] With all six readers populated, watch for `* ignored a bad read (truncated UID)` lines: they may appear, but no phantom `NEW CAR` should. (E-29)
- [ ] Disconnect one space reader's SS wire while running: the other spaces and lanes keep working.

**Serial**
- [ ] `PING` replies `PONG`; `LOT` reprints the lot; `CAR 9 x` and `ORDER abc` reply `* bad car number: 9` / `* bad car number: 0`. (E-34)
- [ ] Paste a 60-character `CAR 1 ...` line: the label is the first 18 characters of the text.
- [ ] Close and reopen the serial monitor: the board resets (DTR), prints the banner again, and has forgotten every car and label (with `REMEMBER 0`). (E-37)
- [ ] Unplug and replug USB with the laptop daemon running: note what the daemon does. (E-36)

**Long and odd text on the LCD**
- [ ] `CAR 1 abcdefghijklmnopqrstuvwxyz`: line shows `1>abcdefghijklmnopqr` (18 characters, nothing wraps onto the next row).
- [ ] `FULLCLR`, three `FULL` lines totalling over 120 characters, then `FULLSHOW 1`: `YOUR ORDER` pages through at most 9 rows, words are not split where a space was available, and the screen returns to the lot after 12 s. (E-16)
- [ ] A label with a non-ASCII byte sent from another tool shows a garbage glyph but does not disturb the other rows. (E-17)

**Persistence (only with `REMEMBER 1`)**
- [ ] Load labels, reset the board: banner shows `EEPROM: restored k car(s)`, and the lot comes back with the same labels once the cars are seen.
- [ ] `FORGET`, reset: `EEPROM: nothing saved yet`.
