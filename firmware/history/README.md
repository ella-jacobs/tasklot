# firmware/history — how the board firmware was built up

These sketches are the steps that led to `firmware/tasklot_full_v2`, kept so the
build-up is visible. None of them is the current build target. Each one compiles for
the Arduino Mega 2560 (`arduino:avr:mega:cpu=atmega2560`) with MFRC522 v1.4.12 and
LiquidCrystal I2C v1.1.2.

They are kept as they were written, apart from removing names and internal file
references, so they do not meet the same code-quality bar as the current sketch.

| Order | Sketch | What it proved |
|---|---|---|
| 1 | `which_car_is_it/` | One RC522 reader can identify a car by its NTAG213 sticker UID, through plywood. Tap a new sticker and it becomes the next car; tap a known one and it says which car it is. |
| 2 | `four_readers_baseline/` | Four RC522 readers can share one SPI bus with a shared reset line (RST on A0, SS on 44 / 45 / 40 / 41). No identity logic, on purpose: when a bigger sketch stops reading, this one separates a wiring or power fault from a code fault. |
| 3 | `which_car_is_it_4/` | The identity layer on top of four readers: arrival, departure (presence pings with `WakeupA` and a 1200 ms timeout), and the lot printed in space order after every change. Space order is the priority list. |
| 4 | `lcd_hello/` | The LCD2004A with an I2C backpack lights up and prints. Scans the I2C bus for the backpack address (0x27 or 0x3F). |
| 5 | `tasklot_full/` | Version 1 of the full board: four spaces, the LCD, and the `CAR` / `DONE` / `CLEAR` / `LOT` / `PING` serial commands so the laptop can send task text. Optional EEPROM persistence behind `#define REMEMBER`. |
| 6 | `lcd_bridge/` | The screen and command half of `tasklot_full` with the readers removed. The laptop sends `PARK` / `LEAVE` / `ORDER` in place of reader events, so the screen logic could be tested before the readers were wired. Runs on an UNO or a Mega. |
| 7 | `six_reader_check/` | Diagnostic for six readers on one bus: reads each reader's `VersionReg`. A good version with no tag reads means the 3.3 V rail is starved, not that the wiring is wrong. |

Version 2 (`firmware/tasklot_full_v2/`) adds the two lane readers, the speaker and the
pickup lane, on top of step 5. See `DESIGN.md` at the repo root.
