// TaskLot v2 - the drive-through.  [Elegoo Mega 2560]
//
// Six RC522 readers on one SPI bus (four parking spaces, a speaker lane, a pickup
// lane), a 20 x 4 LCD on I2C, and a line protocol to the laptop over USB serial at
// 9600 baud. The board maps sticker UIDs to cars and cars to 18-character labels; the
// laptop records, transcribes and shortens the spoken task and sends the label back.
//
// This file only builds the objects and runs the loop. The behaviour lives in:
//   config.h            pins, sizes, timings, the REMEMBER / USE_PRESENCE switches
//   TaskLot             the interaction: what each read and command does
//   RfidSlot            one reader (the bench-verified MFRC522 call sequences)
//   CarRegistry         UID -> car -> label, optional EEPROM persistence
//   ParkingLot          which car is on which space
//   LaneDebouncer       one event per sweep on a lane
//   ReadbackText        the full task text for a read-back, word-wrapped
//   LcdView             everything on the glass: lot, overlays, flashing, paging
//   SerialProtocol      command parsing and the exact event strings
// Arduino compiles every .h/.cpp in this folder with the sketch; no build setup needed.
// firmware/README.md has the state machine, the wire format and the hardware checklist.
//
// Why v2 exists: in v1 the board could not tell "moved to another space" from "driven
// out of the lot", because both look the same to a reader: the space went quiet. So the
// laptop had to decide a task was finished. In v2 the question is answered physically:
// the pickup lane is a sixth reader, and a car only crosses it because a hand carried it
// there. The board still never decides a task is done on its own.
//
// ---------------------------------------------------------------------------
// WIRING (pin numbers are in config.h)
//
//   All six readers:  3.3V -> 3.3V   ** NEVER 5V - it kills the reader **
//                     GND -> GND, RST -> A0 (shared by all six), IRQ not connected
//                     SCK -> 52, MOSI -> 51, MISO -> 50 (shared, fixed hardware SPI)
//   Space 1..4 SS:    44, 45, 40, 41
//   Speaker SS:       37        Pickup SS: 36
//   LCD2004A + I2C:   VCC -> 5V (the LCD wants 5V, the opposite of the readers),
//                     GND -> GND, SDA -> 20, SCL -> 21
//   Leave pin 53 unwired: SPI.begin() drives it on its own.
//
// POWER: the Mega's 3.3V rail is rated 50 mA and six RC522s draw 78-156 mA. Four were
// bench-tested on the internal rail and already ran on margin; six may need an external
// 3.3V regulator fed from 5V. If reads go flaky only when everything is populated, that
// is this. The tell: good version bytes at boot (SPI needs almost no current) but no tag
// reads (the RF field does).
//
// Set the LCD contrast pot before the printed frame goes on; there is no access after.
// Backlight on but no letters means contrast, not a dead screen.
//
// Only one program can hold the serial port, so close the Serial Monitor before running
// the laptop daemon or the browser simulator. Opening the port resets the board.
//
// AI disclosure: written with Claude (Anthropic) to Ella's design - her wiring, her pin
// assignments, her interaction - and later split into classes with Claude. Libraries:
// MFRC522 by miguelbalboa (rfid v1.4.12, public domain); LiquidCrystal_I2C by Frank de
// Brabander (v1.1.2).

#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <SPI.h>
#include <Wire.h>

#include "TaskLot.h"
#include "config.h"

// Every object is a global with a fixed size: no heap, so RAM use is known at link time
// and cannot fragment over a long demo.
RfidSlot space1(PIN_SS_SPACE_1, PIN_RFID_RST);
RfidSlot space2(PIN_SS_SPACE_2, PIN_RFID_RST);
RfidSlot space3(PIN_SS_SPACE_3, PIN_RFID_RST);
RfidSlot space4(PIN_SS_SPACE_4, PIN_RFID_RST);
RfidSlot speaker(PIN_SS_SPEAKER, PIN_RFID_RST);
RfidSlot pickup(PIN_SS_PICKUP, PIN_RFID_RST);

RfidSlot* const spaces[NUM_SPACES] = {&space1, &space2, &space3, &space4};
RfidSlot* const lanes[NUM_LANES] = {&speaker, &pickup};  // LANE_SPEAKER, LANE_PICKUP

SerialProtocol protocol(Serial);
TaskLot taskLot(spaces, lanes, protocol);

void setup() {
  Serial.begin(SERIAL_BAUD);
  taskLot.begin();
}

void loop() {
  taskLot.readCommands();  // the laptop first: it is cheap, and the RX buffer is small
  taskLot.pollSpaces();    // spaces 1-4 in order, then the lanes, so a car carried out
  taskLot.pollLanes();     // of a space is marked gone before a lane sees it
  delay(LOOP_DELAY_MS);    // let the shared SPI bus settle between readers
  taskLot.tickScreen();    // flash, page, expire overlays; never blocks
}
