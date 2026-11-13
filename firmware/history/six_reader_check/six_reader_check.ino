// TaskLot - six_reader_check.  DIAGNOSTIC ONLY - not a build sketch.
//
// Answers one question the baseline cannot: is a silent reader ON THE BUS but
// too weak to energize a tag, or is it not talking at all?
//
// It reads each RC522's VersionReg, which needs almost no current - just SPI.
// Lighting the RF field to read a tag needs a LOT more. So:
//
//   version 0x91 / 0x92  -> genuine board, alive on the bus
//   version 0x88 / 0x12  -> clone board, alive on the bus (fine)
//   version 0x00 / 0xFF  -> NOT TALKING: wiring, SS pin, or no power at all
//
// If a reader reports a good version here but never detects a tag in the
// baseline, the SPI link is fine and the RF field is starved -> that is the
// 3.3V rail, not your wiring. Mega 3.3V pin is rated 50 mA; six RC522s want
// 78-156 mA.
//
// WIRING - same as the baseline:
//   ALL SIX: 3.3V -> 3.3V  ** NEVER 5V **   GND -> GND   RST -> A0
//            SCK -> 52   MOSI -> 51   MISO -> 50   IRQ -> not connected
//   SS: r1=44  r2=45  r3=40  r4=41  r5=36  r6=37
//
// Serial Monitor: 9600 baud.

#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN A0

const byte NUM = 6;
const byte SS_PINS[NUM] = { 44, 45, 40, 41, 36, 37 };

MFRC522 r1(44, RST_PIN), r2(45, RST_PIN), r3(40, RST_PIN),
        r4(41, RST_PIN), r5(36, RST_PIN), r6(37, RST_PIN);
MFRC522* reader[NUM] = { &r1, &r2, &r3, &r4, &r5, &r6 };

void report() {
  Serial.println(F("--------------------------------"));
  for (byte i = 0; i < NUM; i++) {
    byte v = reader[i]->PCD_ReadRegister(MFRC522::VersionReg);

    Serial.print(F("reader "));
    Serial.print(i + 1);
    Serial.print(F("  (SS "));
    Serial.print(SS_PINS[i]);
    Serial.print(F(")  ver 0x"));
    if (v < 0x10) Serial.print('0');
    Serial.print(v, HEX);

    if (v == 0x00 || v == 0xFF) Serial.println(F("   <-- NOT TALKING (wiring / SS / power)"));
    else if (v == 0x91 || v == 0x92) Serial.println(F("   ok - genuine, on the bus"));
    else if (v == 0x88 || v == 0x12) Serial.println(F("   ok - clone, on the bus"));
    else                             Serial.println(F("   ?? unexpected, but it IS answering"));
  }
  Serial.println(F("--------------------------------"));
}

void setup() {
  Serial.begin(9600);
  SPI.begin();

  for (byte i = 0; i < NUM; i++) reader[i]->PCD_Init();

  Serial.println();
  Serial.println(F("=== TaskLot - six reader bus check ==="));
  Serial.println(F("Good version + no tag reads in the baseline = starved 3.3V rail."));
  Serial.println(F("0x00 / 0xFF = that board is not on the bus at all."));
  Serial.println();
  report();
  Serial.println(F("Re-checking every 3s. Unplug things and watch it change."));
}

void loop() {
  delay(3000);
  report();
}
