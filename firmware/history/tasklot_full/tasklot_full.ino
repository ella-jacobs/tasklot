// TaskLot - THE WHOLE THING.  Four spaces + the LCD + task text.  [ELEGOO MEGA 2560]
//
// This is which_car_is_it_4 with two things added: the LCD, and a way for the
// laptop to tell the board what each car's task says.
//
// ** THE VERIFIED PARTS ARE UNCHANGED. ** Same pins, same shared RST, same
// per-reader PCD_Init(), same IsNewCardPresent/ReadCardSerial/HaltA/StopCrypto1
// sequence, same poll order, same GONE_MS. Do not tidy those - they are the part
// that is proven on the bench. Everything new sits on top of them.
//
// ** THE THREE LINES tasklot-live.html PARSES ARE UNCHANGED, WORD FOR WORD. **
//      SPACE n  <- CAR m parked
//      SPACE n  -> CAR m left
//      * NEW CAR registered -> CAR n
// Change that wording and the live page stops updating. New output was ADDED
// (TASK / PONG), never edited in.
//
// ---------------------------------------------------------------------------
// THE IDEA, in one paragraph
//
// Each car is one task. The task text is NOT on the tag - the tag is a key, and
// the board holds UID -> car -> task. The audio never touches the Arduino: the
// laptop records, transcribes and shortens the memo, then sends the board an
// 18-character version of it. Which space a car is parked in IS its priority,
// so space 1 is line 1 of the LCD. Move a car, the list reorders. That is the
// entire interaction.
//
// ---------------------------------------------------------------------------
// WIRING - Elegoo Mega 2560
//
//   ALL FOUR READERS:  3.3V -> 3.3V   ** NEVER 5V - it kills the board **
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
//   LCD2004A + I2C backpack:  VCC -> 5V   ** the LCD wants 5V, the opposite of
//                             GND -> GND     the readers. Do not reuse a 3.3V wire. **
//                             SDA -> 20
//                             SCL -> 21
//
// Leave pin 53 unwired - SPI.begin() drives it on its own.
//
// ** POWER WARNING. ** The Mega's 3.3V rail is rated 50 mA and four RC522s draw
// 52-104 mA. It works, on margin. A fifth reader needs an external 3.3V regulator
// fed from 5V. If reads go flaky only when every space is full, that is this.
//
// ** SET THE CONTRAST POT BEFORE THE PRINTED FRAME GOES ON. ** There is no
// exterior access once it does. Backlight on but no letters = contrast, not a
// dead screen.
//
// ---------------------------------------------------------------------------
// WHAT THE LAPTOP CAN SEND (9600 baud, one command per line)
//
//   CAR <n> <text>   set car n's LCD line. Text is truncated to 18 chars.
//                    Works before the car has ever been tapped.
//   DONE <n>         the task on car n is finished - blank its label. The car is a
//                    KEY, not a container: once a task is done the key is empty and
//                    ready to be recorded onto again. Without this, re-parking a
//                    finished car brings its old task back onto the screen.
//                    (`CAR <n>` with no text does the same thing; DONE just reads
//                    like what it means.)
//   CLEAR            forget every task label (does not forget UIDs)
//   FORGET           wipe the saved EEPROM copy (only meaningful if REMEMBER 1)
//   LOT              reprint the lot
//   PING             -> PONG        (the page uses this to prove the link is up)
//
// ** The board cannot tell "moved to another space" from "driven out of the lot." **
// Both look identical to a reader: the space went quiet. So the board never decides
// a task is done on its own - the laptop does, and says so with DONE.
//
// Sent by tasklot-live.html when you dictate a task, and by
// tools/voice/tasklot_voice.py --push. Only one program can hold the port at a
// time, so close the Serial Monitor before either.
//
// ---------------------------------------------------------------------------
// REMEMBERING ACROSS A POWER CUT  (#define REMEMBER)
//
// Cars and their tasks live in RAM, so **anything that resets the board forgets
// everything** - unplugging USB, a laptop going to sleep, opening the serial
// port. That matters when the laptop is hidden under a table during a demo: if
// the board resets you have to go find the laptop to reload it.
//
// With REMEMBER 1 the car list and the task text are mirrored into the
// ATmega2560's EEPROM (4 KB; this uses ~243 bytes) and restored at boot. Load
// the tasks once, and from then on the board knows them on its own - plug it
// into a USB brick, carry it to the room, and the screen comes up already right.
//
// ** It ships as 0. ** Turn it on only AFTER tasklot_full has run correctly once
// without it. Do not debug unproven code on top of unproven code.
//   FORGET  wipes the EEPROM (also what to send if the saved list goes stale).
//
// Serial Monitor: 9600 baud.
//
// AI disclosure: written with Claude (Anthropic) on Ella's wiring and design
// decisions. The MFRC522 library is miguelbalboa/rfid v1.4.12 (public domain);
// LiquidCrystal_I2C is Frank de Brabander's. Credit all of it in the critique.

#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <EEPROM.h>

// Remember cars and tasks across a reset. Ships OFF - see the note above.
// Turn it on only after the sketch has run correctly once with it off.
#define REMEMBER 0

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

const byte NUM_SPACES = 4;
MFRC522* space[NUM_SPACES] = { &rfid1, &rfid2, &rfid3, &rfid4 };

// ---- the car list: UID -> car number. Shared across all four spaces, so car 3
// ---- is car 3 no matter where it parks. RAM only; reset the board and it's empty.
const byte MAX_CARS = 8;
byte known[MAX_CARS][10];
byte knownLen[MAX_CARS];
byte carCount = 0;

// ---- the task text, one line per car. 18 chars because "1>" eats two of the
// ---- twenty. The laptop does the shortening; the board just stores what it's told.
const byte LCD_COLS = 20;
const byte LCD_ROWS = 4;
const byte TASK_LEN = 18;
char taskOf[MAX_CARS][TASK_LEN + 1];

// ---- what each space is holding right now ----
int  occupant[NUM_SPACES];
unsigned long lastSeen[NUM_SPACES];
const unsigned long GONE_MS = 1200;

// ---- the LCD ----
LiquidCrystal_I2C lcd(0x27, LCD_COLS, LCD_ROWS);
byte lcdAddress = 0;                 // 0 = no screen; the sketch runs anyway
char shown[LCD_ROWS][LCD_COLS + 1];  // what's physically on the glass right now

// ---- inbound command buffer ----
char cmd[48];
byte cmdLen = 0;

// ===========================================================================
// EEPROM - the car list and the task text, so a reset isn't amnesia
//
// Layout: [magic][version][carCount] then MAX_CARS x { uidLen, uid[10], task[19] }
// = 3 + 8*30 = 243 bytes of the ATmega2560's 4096. The magic byte is why a blank
// or unrelated EEPROM doesn't load as eight garbage cars.
//
// EEPROM.update() only writes a byte that actually changed - EEPROM is good for
// ~100,000 writes per cell and printLot() runs on every event, so blind writes
// would be a slow way to wear the chip out.
// ===========================================================================
#if REMEMBER
const byte EE_MAGIC = 0x7A;
const byte EE_VERSION = 1;
const int  EE_PER_CAR = 1 + 10 + (TASK_LEN + 1);
int eeCarBase(byte c) { return 3 + c * EE_PER_CAR; }

void saveHeader() {
  EEPROM.update(0, EE_MAGIC);
  EEPROM.update(1, EE_VERSION);
  EEPROM.update(2, carCount);
}

void saveCar(byte c) {
  int at = eeCarBase(c);
  EEPROM.update(at, knownLen[c]);
  for (byte b = 0; b < 10; b++) EEPROM.update(at + 1 + b, known[c][b]);
  for (byte i = 0; i <= TASK_LEN; i++) EEPROM.update(at + 11 + i, taskOf[c][i]);
}

void saveAll() {
  saveHeader();
  for (byte c = 0; c < carCount; c++) saveCar(c);
}

void forgetAll() {
  EEPROM.update(0, 0xFF);          // one byte kills the magic; no need to wipe 243
  Serial.println(F("* EEPROM forgotten - reset the board to start clean"));
}

void loadAll() {
  if (EEPROM.read(0) != EE_MAGIC || EEPROM.read(1) != EE_VERSION) {
    Serial.println(F("EEPROM: nothing saved yet"));
    return;
  }
  byte n = EEPROM.read(2);
  if (n > MAX_CARS) { Serial.println(F("EEPROM: bad count, ignoring")); return; }
  carCount = n;
  for (byte c = 0; c < carCount; c++) {
    int at = eeCarBase(c);
    knownLen[c] = EEPROM.read(at);
    if (knownLen[c] > 10) knownLen[c] = 10;         // never overrun known[c]
    for (byte b = 0; b < 10; b++) known[c][b] = EEPROM.read(at + 1 + b);
    for (byte i = 0; i <= TASK_LEN; i++) taskOf[c][i] = EEPROM.read(at + 11 + i);
    taskOf[c][TASK_LEN] = '\0';                     // whatever was there, end it
  }
  Serial.print(F("EEPROM: restored "));
  Serial.print(carCount);
  Serial.println(F(" car(s) and their tasks"));
}
#else
void saveAll() {}
void saveCar(byte c) { (void)c; }
void loadAll() {}
void forgetAll() { Serial.println(F("* REMEMBER is off - nothing is saved")); }
#endif

// ===========================================================================
void setup() {
  Serial.begin(9600);
  SPI.begin();
  Wire.begin();

  for (byte c = 0; c < MAX_CARS; c++) taskOf[c][0] = '\0';
  for (byte r = 0; r < LCD_ROWS; r++) shown[r][0] = '\0';

  rfid1.PCD_Init();
  rfid2.PCD_Init();
  rfid3.PCD_Init();
  rfid4.PCD_Init();

  Serial.println();
  Serial.println(F("=== TaskLot - four spaces, one screen ==="));

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

  startLcd();
  loadAll();

  Serial.println(F("Park a car on any space. New stickers get a car number."));
  Serial.println(F("Send: CAR <n> <text> | CLEAR | LOT | PING"));
  Serial.println();
  printLot();
}

void loop() {
  readCommands();                       // the laptop talks first - it's cheap

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

// ===========================================================================
// The LCD
// ===========================================================================

// The backpack is 0x27 or 0x3F and there is no way to tell by looking, so scan.
// If nothing answers, say so once and carry on - a missing screen must not take
// the readers down with it.
void startLcd() {
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0 && (a == 0x27 || a == 0x3F)) { lcdAddress = a; break; }
  }
  if (!lcdAddress) {
    Serial.println(F("LCD: none found. Check 5V, GND, SDA->20, SCL->21."));
    Serial.println(F("     Readers still work; the lot prints to Serial only."));
    return;
  }
  Serial.print(F("LCD: 0x"));
  Serial.println(lcdAddress, HEX);

  lcd = LiquidCrystal_I2C(lcdAddress, LCD_COLS, LCD_ROWS);
  lcd.init();
  lcd.backlight();
  lcd.clear();
}

// Write one row, but only if it actually changed. I2C is slow and the loop calls
// this every time anything moves; blind rewrites make the screen flicker.
// The text is padded to the full width - a short write leaves the tail of the
// previous line sitting on the glass.
void lcdRow(byte row, const char* text) {
  char line[LCD_COLS + 1];
  byte i = 0;
  for (; i < LCD_COLS && text[i]; i++) line[i] = text[i];
  for (; i < LCD_COLS; i++) line[i] = ' ';
  line[LCD_COLS] = '\0';

  if (strcmp(line, shown[row]) == 0) return;
  strcpy(shown[row], line);
  if (!lcdAddress) return;
  lcd.setCursor(0, row);
  lcd.print(line);
}

// ===========================================================================
// The lot, top space first. THIS IS THE PRIORITY LIST.
//
// Space order is priority order - space 1 is line 1 - so moving a car between
// spaces is how you reorder the list. That is the whole tangible interface:
// there is no sort button, you pick the car up.
//
// Prints to Serial (for the log on the live page) and to the LCD, same text.
// ===========================================================================
void printLot() {
  Serial.println(F("--------------------"));   // 20 chars = the LCD's width
  for (byte s = 0; s < NUM_SPACES; s++) {
    char line[LCD_COLS + 1];
    line[0] = '1' + s;
    line[1] = '>';

    const char* what = "-";
    if (occupant[s] >= 0) {
      what = taskOf[occupant[s]];
      if (!what[0]) what = NULL;              // parked, but no task recorded yet
    }

    byte i = 0;
    if (what) {
      for (; i < LCD_COLS - 2 && what[i]; i++) line[2 + i] = what[i];
    } else {
      // no text for this car yet - fall back to the car number so the space
      // still reads as occupied instead of looking empty
      line[2] = 'C'; line[3] = 'A'; line[4] = 'R'; line[5] = ' ';
      line[6] = '1' + occupant[s];
      i = 5;
    }
    line[2 + i] = '\0';

    Serial.println(line);
    lcdRow(s, line);
  }
  Serial.println(F("--------------------"));
}

// ===========================================================================
// Commands from the laptop
// ===========================================================================
void readCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      cmd[cmdLen] = '\0';
      if (cmdLen) runCommand(cmd);
      cmdLen = 0;
      continue;
    }
    if (cmdLen < sizeof(cmd) - 1) cmd[cmdLen++] = c;
    // Over-long lines are truncated, not dropped - the tail just gets lost,
    // which is what an 18-char screen was going to do anyway.
  }
}

void runCommand(char* line) {
  if (strncmp(line, "PING", 4) == 0) { Serial.println(F("PONG")); return; }

  if (strncmp(line, "LOT", 3) == 0) { printLot(); return; }

  if (strncmp(line, "FORGET", 6) == 0) { forgetAll(); return; }

  if (strncmp(line, "CLEAR", 5) == 0) {
    for (byte c = 0; c < MAX_CARS; c++) { taskOf[c][0] = '\0'; saveCar(c); }
    Serial.println(F("* tasks cleared"));
    printLot();
    return;
  }

  // DONE <n> - the task is finished, so the car goes back to being a blank key.
  if (strncmp(line, "DONE ", 5) == 0) {
    int n = atoi(line + 5);
    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    taskOf[n - 1][0] = '\0';
    saveCar(n - 1);
    Serial.print(F("TASK "));      // echo an empty label, same shape as any other
    Serial.print(n);               // label change, so the page updates the same way
    Serial.println(' ');
    printLot();
    return;
  }

  // CAR <n> <text>
  if (strncmp(line, "CAR ", 4) == 0) {
    char* p = line + 4;
    while (*p == ' ') p++;
    int n = atoi(p);                       // 1-based car number
    while (*p && *p != ' ') p++;           // step over the digits
    while (*p == ' ') p++;                 // and the gap

    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    byte c = n - 1;
    byte i = 0;
    for (; i < TASK_LEN && p[i]; i++) taskOf[c][i] = p[i];
    taskOf[c][i] = '\0';
    saveCar(c);

    Serial.print(F("TASK "));              // echo, so the page can confirm the
    Serial.print(n);                       // round trip actually landed
    Serial.print(' ');
    Serial.println(taskOf[c]);
    printLot();
    return;
  }

  Serial.print(F("* unknown command: "));
  Serial.println(line);
}

// ===========================================================================
// Readers - unchanged from the verified sketch
// ===========================================================================

// Nothing parked here - is a car arriving?
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
    // A car can only be in one space. If it was parked elsewhere, that space is
    // now empty - this is what makes "pick it up and move it" reorder the list
    // instead of duplicating the task onto two lines.
    for (byte o = 0; o < NUM_SPACES; o++) {
      if (o != s && occupant[o] == car) {
        Serial.print(F("SPACE "));
        Serial.print(o + 1);
        Serial.print(F("  -> CAR "));
        Serial.print(car + 1);
        Serial.println(F(" left"));
        occupant[o] = -1;
      }
    }

    Serial.print(F("SPACE "));
    Serial.print(s + 1);
    Serial.print(F("  <- CAR "));
    Serial.print(car + 1);
    Serial.println(F(" parked"));
    printLot();
  }
}

// A car is parked here - is it still on the pad?
//
// HaltA puts the tag to sleep, and a sleeping tag ignores the normal "any NEW
// card?" question - which is why arrival detection alone can never tell you a car
// is STILL there. So ping with WakeupA, which a halted tag does answer, then put
// it straight back to sleep.
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

// ===========================================================================
// Identity
// ===========================================================================

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
  saveCar(carCount - 1);
  saveAll();
  return carCount - 1;
}

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
