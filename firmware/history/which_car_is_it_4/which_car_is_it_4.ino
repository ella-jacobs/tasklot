// TaskLot - WHICH CAR IS IT.  Four parking spaces.  [ELEGOO MEGA 2560]
//
// Built directly on the 4-reader sketch that is confirmed working on the bench.
// The parts that work are UNCHANGED: same pins, same shared RST, same per-reader
// PCD_Init(), same IsNewCardPresent/ReadCardSerial/HaltA/StopCrypto1 sequence,
// same poll order. Do not "clean those up" - they are the verified part.
//
// What is added on top is the identity layer:
//   tap a new sticker   -> it becomes the next car
//   tap a known sticker -> it says which car it is AND which space it's in
//   lift the car off    -> that space reports empty
//   after every change  -> it prints the lot, top space first
//
// That last line is the project. Parked order IS the priority ranking, and four
// spaces is exactly four LCD lines. The block printLot() writes is what the 2004
// LCD will show, one space per line.
//
// WIRING - Elegoo Mega 2560:
//   ALL FOUR readers:  3.3V -> 3.3V   ** NEVER 5V - it kills the board **
//                      GND  -> GND
//                      RST  -> A0     (shared by all four)
//                      SCK  -> 52     (shared - fixed hardware SPI)
//                      MOSI -> 51     (shared - fixed)
//                      MISO -> 50     (shared - fixed)
//                      IRQ  -> not connected
//
//   Space 1: SDA/SS -> 44     Space 3: SDA/SS -> 40
//   Space 2: SDA/SS -> 45     Space 4: SDA/SS -> 41
//
// SHARED RST IS FINE, with one consequence: you cannot reset one reader without
// resetting all four. If a single reader goes quiet, the reset is all-or-nothing.
//
// ** POWER WARNING - read this before adding a fifth reader. **
// The Mega's 3.3V rail is rated 50 mA. Each RC522 draws 13-26 mA. Four of them is
// 52-104 mA, so this is ALREADY over the rated draw - it works, but it is running
// on margin. A fifth space will need an external 3.3V regulator fed from 5V, not
// the Mega's own 3.3V pin. If reads go flaky only when all spaces are full, that
// is this, not your code.
//
// Serial Monitor: 9600 baud.

#include <SPI.h>
#include <MFRC522.h>

// Set to 0 if departure detection misbehaves at the bench and you just need
// identity to work for the demo. Arrivals keep working either way.
#define USE_PRESENCE 1

#define RST_PIN A0

#define SS_PIN1 44
#define SS_PIN2 45
#define SS_PIN3 40
#define SS_PIN4 41

MFRC522 rfid1(SS_PIN1, RST_PIN);
MFRC522 rfid2(SS_PIN2, RST_PIN);
MFRC522 rfid3(SS_PIN3, RST_PIN);
MFRC522 rfid4(SS_PIN4, RST_PIN);

// Same four objects, in an array, so the logic below can loop over them
// instead of being written out four times.
const byte NUM_SPACES = 4;
MFRC522* space[NUM_SPACES] = { &rfid1, &rfid2, &rfid3, &rfid4 };

// ---- the car list: UID -> car number. Shared across all four spaces, so
// ---- car 3 is car 3 no matter where it parks. Lives in RAM only; reset the
// ---- board and it's empty.
const byte MAX_CARS = 8;
byte known[MAX_CARS][10];   // stored UIDs
byte knownLen[MAX_CARS];    // how many bytes each UID is
byte carCount = 0;

// ---- what each space is holding right now ----
int  occupant[NUM_SPACES];             // car index parked here, or -1 for empty
unsigned long lastSeen[NUM_SPACES];
const unsigned long GONE_MS = 1200;    // silent this long -> the car really left

void setup() {
  Serial.begin(9600);
  SPI.begin();

  rfid1.PCD_Init();
  rfid2.PCD_Init();
  rfid3.PCD_Init();
  rfid4.PCD_Init();

  Serial.println();
  Serial.println(F("=== TaskLot - which car is it - 4 spaces ==="));

  // Boot check. 0x91/0x92 = genuine, 0x88/0x12 = clone (fine),
  // 0x00 or 0xFF = that reader is not talking. Find out here, not mid-demo.
  for (byte s = 0; s < NUM_SPACES; s++) {
    occupant[s] = -1;
    lastSeen[s] = 0;

    byte v = space[s]->PCD_ReadRegister(MFRC522::VersionReg);
    Serial.print(F("space "));
    Serial.print(s + 1);
    Serial.print(F(" reader: 0x"));
    if (v < 0x10) Serial.print('0');
    Serial.print(v, HEX);
    Serial.println((v == 0x00 || v == 0xFF) ? F("   <-- NOT TALKING") : F("   ok"));
  }

  Serial.println(F("Park a car on any space. New stickers get a car number."));
  Serial.println();
  printLot();
}

void loop() {
  for (byte s = 0; s < NUM_SPACES; s++) {
#if USE_PRESENCE
    if (occupant[s] < 0) checkArrival(s);
    else                 checkStillThere(s);
#else
    checkArrival(s);
#endif
  }
  delay(60);   // let the shared bus breathe between readers
}

// ---------------------------------------------------------------------------
// Nothing parked here - is a car arriving?
// This is the verified detection sequence, unchanged.
// ---------------------------------------------------------------------------
void checkArrival(byte s) {
  MFRC522 &rfid = *space[s];

  if (!(rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial())) return;

  int car = findCar(rfid);
  if (car < 0) {
    car = addCar(rfid);
    if (car < 0) {
      Serial.println(F("  no car slots left - reset the board to clear"));
      rfid.PICC_HaltA();
      rfid.PCD_StopCrypto1();
      return;
    }
    Serial.print(F("* NEW CAR registered -> CAR "));
    Serial.print(car + 1);
    Serial.print(F("   UID "));
    printUID(rfid);
  }

  bool changed = (occupant[s] != car);
  occupant[s] = car;
  lastSeen[s] = millis();

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  if (changed) {
    Serial.print(F("SPACE "));
    Serial.print(s + 1);
    Serial.print(F("  <- CAR "));
    Serial.print(car + 1);
    Serial.println(F(" parked"));
    printLot();
  }
}

// ---------------------------------------------------------------------------
// A car is parked here - is it still on the pad?
//
// HaltA puts the tag to sleep, and a sleeping tag ignores the normal
// "any NEW card?" question - which is why arrival detection alone can never
// tell you a car is STILL there. So ping with WakeupA, which a halted tag does
// answer, then put it straight back to sleep.
// ---------------------------------------------------------------------------
void checkStillThere(byte s) {
  MFRC522 &rfid = *space[s];

  byte atqa[2];
  byte size = sizeof(atqa);
  MFRC522::StatusCode st = rfid.PICC_WakeupA(atqa, &size);
  bool here = (st == MFRC522::STATUS_OK || st == MFRC522::STATUS_COLLISION);
  rfid.PICC_HaltA();

  if (here) {
    lastSeen[s] = millis();
    return;
  }
  if (millis() - lastSeen[s] < GONE_MS) return;   // one missed ping isn't a departure

  Serial.print(F("SPACE "));
  Serial.print(s + 1);
  Serial.print(F("  -> CAR "));
  Serial.print(occupant[s] + 1);
  Serial.println(F(" left"));

  occupant[s] = -1;
  printLot();
}

// ---------------------------------------------------------------------------
// The lot, top space first. THIS IS THE LCD - four spaces, four lines.
// Swap "CAR n" for the task text once tasks are recorded and this block is
// literally what gets written to the 2004 display.
// ---------------------------------------------------------------------------
void printLot() {
  Serial.println(F("--------------------"));   // 20 chars = the LCD's width
  for (byte s = 0; s < NUM_SPACES; s++) {
    Serial.print(s + 1);
    Serial.print(F(". "));
    if (occupant[s] < 0) Serial.println(F("-"));
    else {
      Serial.print(F("CAR "));
      Serial.println(occupant[s] + 1);
    }
  }
  Serial.println(F("--------------------"));
}

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

// Do we already know this UID?
int findCar(MFRC522 &rfid) {
  for (byte i = 0; i < carCount; i++) {
    if (knownLen[i] != rfid.uid.size) continue;
    bool same = true;
    for (byte b = 0; b < knownLen[i]; b++) {
      if (known[i][b] != rfid.uid.uidByte[b]) { same = false; break; }
    }
    if (same) return i;
  }
  return -1;
}

// Remember a UID we've never seen before
int addCar(MFRC522 &rfid) {
  if (carCount >= MAX_CARS) return -1;
  knownLen[carCount] = rfid.uid.size;
  for (byte b = 0; b < rfid.uid.size; b++) {
    known[carCount][b] = rfid.uid.uidByte[b];
  }
  carCount++;
  return carCount - 1;
}

// Unchanged from the working sketch.
void printUID(MFRC522 &rfid) {
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      Serial.print("0");
    }
    Serial.print(rfid.uid.uidByte[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
}
