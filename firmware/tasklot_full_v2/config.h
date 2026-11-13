// config.h - every pin, size, timing and feature switch the TaskLot board uses.
//
// Role: the one place to look when the wiring or a threshold changes. Every other file
// in this sketch includes it; nothing else defines a pin or a magic number.
//
// The two feature switches are plain #defines so they can be flipped by editing this
// file (the host tests flip them the same way). Both are guarded with #ifndef so a
// build can also override them from the command line.

#ifndef TASKLOT_CONFIG_H
#define TASKLOT_CONFIG_H

#include <Arduino.h>

// ---------------------------------------------------------------------------
// Feature switches
// ---------------------------------------------------------------------------

// Mirror the car list and labels into EEPROM and restore them at boot, so a reset (USB
// unplugged, the serial port reopened) does not wipe the lot. Ships OFF: turn it on only
// after the sketch has run correctly with it off, so unproven persistence code is never
// debugged on top of an unproven board.
#ifndef REMEMBER
#define REMEMBER 0
#endif

// Detect cars leaving the four spaces with presence pings. Set to 0 if departures
// misbehave on the bench and only identity is needed; arrivals keep working. The two
// lanes are arrival-only either way.
#ifndef USE_PRESENCE
#define USE_PRESENCE 1
#endif

// ---------------------------------------------------------------------------
// Pins (Elegoo Mega 2560). SCK 52, MOSI 51, MISO 50 are the fixed hardware SPI pins
// and are not configurable; the LCD is on the fixed I2C pins SDA 20 / SCL 21.
// ---------------------------------------------------------------------------

// All six readers share one reset line, so resetting one resets all of them.
const byte PIN_RFID_RST = A0;

// Chip-select (SDA/SS) pin of each reader. Space 1 is the top line of the lot.
const byte PIN_SS_SPACE_1 = 44;
const byte PIN_SS_SPACE_2 = 45;
const byte PIN_SS_SPACE_3 = 40;
const byte PIN_SS_SPACE_4 = 41;
// The lane pins are as defined in the code that ran on the bench. An older comment
// had them the other way round; see DESIGN.md open question 9.1.
const byte PIN_SS_SPEAKER = 37;
const byte PIN_SS_PICKUP = 36;

// ---------------------------------------------------------------------------
// Sizes
// ---------------------------------------------------------------------------

const byte NUM_SPACES = 4;
const byte NUM_LANES = 2;
const byte LANE_SPEAKER = 0;  // index into the lane arrays
const byte LANE_PICKUP = 1;

// Distinct cars remembered until reset. The laptop assumes the same limit.
const byte MAX_CARS = 8;

// A car index that means "no car" (empty space, no order open, nothing playing).
const int8_t NO_CAR = -1;

// MFRC522 UIDs are 4, 7 or 10 bytes; the stickers are NTAG213 (7 bytes).
const byte UID_MAX_LEN = 10;

const byte LCD_COLS = 20;
const byte LCD_ROWS = 4;

// A lot line is "1>" plus the label, so the label gets the other 18 columns.
const byte TASK_LEN = 18;

// Read-back text sent with FULL chunks, and the rows it wraps into: 3 pages of 3 rows
// under the "YOUR ORDER" title row.
const byte FULL_LEN = 120;
const byte WRAP_LINES = 9;
const byte READBACK_ROWS_PER_PAGE = 3;

// Inbound command line, including the terminating NUL. Longer lines are truncated:
// the tail is lost, which an 18-character label would have cut anyway.
const byte CMD_BUFFER_LEN = 48;

// ---------------------------------------------------------------------------
// Serial and LCD
// ---------------------------------------------------------------------------

const unsigned long SERIAL_BAUD = 9600;

// The I2C backpack ships at one of these two addresses and there is no way to tell by
// looking, so boot scans the bus for either.
const byte LCD_ADDR_A = 0x27;
const byte LCD_ADDR_B = 0x3F;
const byte I2C_FIRST_ADDR = 1;    // 0 is the general-call address
const byte I2C_END_ADDR = 127;    // scan stops before this

// ---------------------------------------------------------------------------
// Timing (milliseconds)
// ---------------------------------------------------------------------------

// Pause at the end of every loop so the shared SPI bus settles between readers.
const uint32_t LOOP_DELAY_MS = 60;

// A space is empty only after this long with no answer to a presence ping, so one
// missed ping is not a departure.
const uint32_t GONE_MS = 1200;

// The same car re-read on a lane inside this window is the same pass. Comfortably
// longer than a hand takes to sweep a car across a reader (about 0.5-1 s), short
// enough that going back for a second order never feels blocked.
const uint32_t LANE_COOLDOWN_MS = 2000;

const uint32_t FLASH_SLOW_MS = 500;   // "ORDER IN PROGRESS": a steady pulse
const uint32_t FLASH_FAST_MS = 220;   // announcements: urgent, then gone
const uint32_t ANNOUNCE_MS = 1600;    // long enough to read, short enough not to drag
const uint32_t PAGE_MS = 2500;        // long enough to read three rows
const uint32_t PLAY_MS = 12000;       // a read-back falls back to the lot on its own

#endif  // TASKLOT_CONFIG_H
