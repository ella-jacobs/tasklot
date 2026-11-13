// TaskLot v2 - THE DRIVE-THROUGH.  Six readers: four spaces, a speaker, a pickup
// lane.  Plus the LCD and the task text.  [ELEGOO MEGA 2560]
//
// This is tasklot_full with two more readers on the same SPI bus, and the
// interaction those two readers buy.
//
// ** THE VERIFIED PARTS ARE UNCHANGED. ** Same pins, same shared RST, same
// per-reader PCD_Init(), same IsNewCardPresent/ReadCardSerial/HaltA/StopCrypto1
// sequence, same poll order for spaces 1-4, same GONE_MS. Do not tidy those -
// they are the part that is proven on the bench. Everything new sits on top.
//
// ** THE THREE LINES THE LIVE PAGE PARSES ARE UNCHANGED, WORD FOR WORD. **
//      SPACE n  <- CAR m parked
//      SPACE n  -> CAR m left
//      * NEW CAR registered -> CAR n
// New output was ADDED, never edited in. v2 adds exactly two more:
//      SPEAKER  CAR n ordering
//      PICKUP   CAR n collected
//
// ---------------------------------------------------------------------------
// THE IDEA, in one paragraph
//
// You order a task the way you order a burger. Each car is one task, and the
// tag is a KEY, not a container - the board holds UID -> car -> task, the text
// never lives on the sticker. Drive a car past THE SPEAKER and you are placing
// an order: the laptop starts recording and the screen belongs to that order.
// PARK IT IN A SPACE and the order ends - coming to rest IS the stop gesture,
// which is why there is deliberately no stop button and no stop command. The
// space it lands in is its priority: space 1 is line 1. Move it to another
// space and the list reorders, because a car can only hold one space at a time.
// Drive it into the PICKUP LANE and the order is collected: the label is
// blanked and the car is a clean key again, ready to order.
//
// There is no read-back step. Playback was cut on purpose - the screen already
// says what every car is holding, and a fifth gesture was a fifth thing to
// explain in a two-minute demo.
//
// ---------------------------------------------------------------------------
// WHY v2 EXISTS - the one thing v1 could not do
//
// ** In v1 the board could not tell "moved to another space" from "driven out
// of the lot." ** Both look identical to a reader: the space simply went quiet.
// So v1 could never decide a task was finished; the laptop had to decide, and
// say so with DONE.
//
// ** The board still never decides a task is done on its own. ** It does not
// guess, and silence still means nothing. What changed is that the question is
// now answered PHYSICALLY: the pickup lane is a sixth reader, and a car only
// crosses it because a hand carried it there. A quiet space is still just a
// quiet space. A read on pin 37 is a person saying "this one is finished." That
// distinction - a done-ness you perform with your hand instead of a done-ness
// the software infers - is the whole reason for v2: one more reader removed a
// command, a button, and an inference.
//
// ---------------------------------------------------------------------------
// WIRING - Elegoo Mega 2560
//
//   ALL SIX READERS:   3.3V -> 3.3V   ** NEVER 5V - it kills the board **
//                      GND  -> GND
//                      RST  -> A0     (shared by all six)
//                      SCK  -> 52     (shared - fixed hardware SPI)
//                      MOSI -> 51     (shared - fixed)
//                      MISO -> 50     (shared - fixed)
//                      IRQ  -> not connected
//
//   Space 1: SDA/SS -> 44     Space 3: SDA/SS -> 40
//   Space 2: SDA/SS -> 45     Space 4: SDA/SS -> 41
//   SPEAKER: SDA/SS -> 36     PICKUP:  SDA/SS -> 37
//
//   (Pins 36 and 37 confirmed by firmware/six_reader_check.)
//
//   LCD2004A + I2C backpack:  VCC -> 5V   ** the LCD wants 5V, the opposite of
//                             GND -> GND     the readers. Do not reuse a 3.3V wire. **
//                             SDA -> 20
//                             SCL -> 21
//
// Leave pin 53 unwired - SPI.begin() drives it on its own.
//
// ** POWER WARNING - READ THIS ONE. ** The Mega's 3.3V rail is rated 50 mA.
// SIX RC522s draw 78-156 mA. FOUR (52-104 mA) is what has actually been
// bench-tested, and that already ran on margin. Six on the internal rail is
// UNVERIFIED and may need an external 3.3V regulator fed from 5V.
// ** If reads go flaky only when everything is populated, that is this. **
// The tell: six_reader_check reports good VersionRegs (SPI needs almost no
// current) but tags do not read (the RF field does). Good version + no reads =
// starved rail, not bad wiring.
//
// ** SET THE CONTRAST POT BEFORE THE PRINTED FRAME GOES ON. ** There is no
// exterior access once it does. Backlight on but no letters = contrast, not a
// dead screen.
//
// ---------------------------------------------------------------------------
// WHAT THE LAPTOP CAN SEND (9600 baud, one command per line) - UNCHANGED from v1
//
//   CAR <n> <text>   set car n's LCD line. Text is truncated to 18 chars.
//                    Works before the car has ever been tapped.
//   DONE <n>         blank car n's label. The pickup lane now does this from the
//                    hardware side, so DONE is a manual override / a way for the
//                    laptop to clean up - not the normal path any more.
//   CLEAR            forget every task label (does not forget UIDs)
//   FORGET           wipe the saved EEPROM copy (only meaningful if REMEMBER 1)
//   LOT              reprint the lot
//   PING             -> PONG        (the page uses this to prove the link is up)
//   ORDER <n>        pretend car n drove past the speaker. The SPEAKER READER does
//                    this on the real build; the command exists so tools/sim can
//                    still drive the board when a reader is not available.
//
// There is still no stop command, and v2 does not add one. Parking stops the
// order. That is a design decision, not an omission.
//
// Only one program can hold the port at a time, so close the Serial Monitor
// before running tasklot-live.html or tools/voice/tasklot_voice.py --push.
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
// ** It ships as 0. ** Turn it on only AFTER this sketch has run correctly once
// without it. Do not debug unproven code on top of unproven code.
//   FORGET  wipes the EEPROM (also what to send if the saved list goes stale).
//
// Serial Monitor: 9600 baud.
//
// AI disclosure: written with Claude (Anthropic) to Ella's design - her wiring,
// her pin assignments, her interaction. The reader layer is lifted unchanged
// from the bench-verified tasklot_full; the screen layer is lifted unchanged
// from lcd_bridge. Libraries: MFRC522 is miguelbalboa/rfid v1.4.12 (public
// domain); LiquidCrystal_I2C is Frank de Brabander's. Credit all of it in the
// critique.

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
// (This only ever applied to the four SPACES. The speaker and the pickup lane
// are arrival-only by nature and are not affected by it.)
#define USE_PRESENCE 1

#define RST_PIN A0

#define SS_PIN1 44
#define SS_PIN2 45
#define SS_PIN3 40
#define SS_PIN4 41
#define SS_SPEAKER 37
#define SS_PICKUP  36

MFRC522 rfid1(SS_PIN1, RST_PIN);
MFRC522 rfid2(SS_PIN2, RST_PIN);
MFRC522 rfid3(SS_PIN3, RST_PIN);
MFRC522 rfid4(SS_PIN4, RST_PIN);
MFRC522 rfidSpeaker(SS_SPEAKER, RST_PIN);
MFRC522 rfidPickup(SS_PICKUP, RST_PIN);

const byte NUM_SPACES = 4;
MFRC522* space[NUM_SPACES] = { &rfid1, &rfid2, &rfid3, &rfid4 };

// ---- THE LANES ----------------------------------------------------------
// A space is somewhere a car COMES TO REST. A lane is somewhere a car DRIVES
// PAST. That difference is the whole reason these two readers are handled by
// separate code: they use arrival detection ONLY. They are never presence-
// tracked, they never own an occupant slot, and they never appear on the lot.
// Nothing "is parked at the speaker" - you cannot be in the drive-through.
const byte NUM_LANES = 2;
const byte LANE_SPEAKER = 0;
const byte LANE_PICKUP  = 1;
MFRC522* lane[NUM_LANES] = { &rfidSpeaker, &rfidPickup };

// ---- lane debounce ------------------------------------------------------
// A tag sitting in a reader's field answers PICC_IsNewCardPresent() over and
// over - HaltA sleeps it, but the next loop wakes it and it looks new again.
// On a SPACE that is exactly what you want (it is how presence works). On a
// LANE it is a bug: one hand-pass would fire ten times, spamming the serial
// line and restarting the recording on the laptop mid-sentence.
//
// So each lane remembers the last car it saw and when. The SAME car re-read
// inside the cooldown is the same pass and is ignored; a DIFFERENT car is
// always a new event and goes through immediately. 2000 ms is chosen to be
// comfortably longer than a human hand takes to sweep a car across a reader
// (~0.5-1 s) but short enough that deliberately going back for a second order
// on the same car never feels blocked.
const unsigned long LANE_COOLDOWN_MS = 2000;
int           lastLaneCar[NUM_LANES];
unsigned long lastLaneAt[NUM_LANES];

// ---- the car list: UID -> car number. Shared across all six readers, so car 3
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

// ---- an order in progress. -1 = nobody is at the speaker.
// The lot is not shown while an order is open; the screen belongs to the order,
// which is what makes driving past the speaker a visible event from across a room.
int ordering = -1;

// ---- a read-back in progress. -1 = nothing is playing.
// THE SPEAKER HAS TWO JOBS, and the CAR decides which. A blank car is placing an
// order. A car that already carries a task is having it READ BACK - which is what
// a real drive-through speaker does: it takes your order, then repeats it to you.
// The board owns the SCREEN for this; the LAPTOP does the talking, because the
// board holds 18 characters and a read-back is a whole sentence.
int playing = -1;

// ---------------------------------------------------------------------------
// THE SCREEN OVERLAYS — and why the flashing is non-blocking.
//
// Two moments in the interaction get the whole screen, and both FLASH so they
// read from across a room:
//
//   ORDER IN PROGRESS   while you are talking at the speaker
//   ORDER IS IN         the beat after you park, before the list reorganises
//
// ** THE FLASH MUST NOT USE delay(). ** The AVR's serial RX buffer is 64 bytes
// and the laptop keeps talking while the screen is busy; a blocking flash would
// drop bytes and merge commands (see DESIGN.md, serial pacing). So the overlay is a
// state + a timestamp, loop() ticks it, and readCommands() keeps running the
// whole time. Serial output is never held back either: the lot is printed to
// Serial immediately, and only the GLASS waits.
//
// ORDER IS IN only fires when a task was actually just recorded — an order was
// open when the car parked. Moving an already-loaded car between spaces just
// reorders, with no announcement.
// ---------------------------------------------------------------------------
enum Overlay { OV_NONE, OV_ORDERING, OV_PLAYING, OV_ANNOUNCE };
Overlay overlay = OV_NONE;

unsigned long overlayUntil = 0;    // OV_ANNOUNCE only: when to fall back to the lot
const char*   announceMsg  = "";   // what the announcement says
unsigned long flashAt      = 0;    // last time the flash phase flipped
bool          flashOn      = true;

const unsigned long FLASH_SLOW_MS = 500;   // "ORDER IN PROGRESS" — a steady pulse
const unsigned long FLASH_FAST_MS = 220;   // announcements — urgent, then gone
const unsigned long ANNOUNCE_MS   = 1600;  // long enough to read, short enough to not drag

// The lot as four rendered rows, kept so the glass can be repainted after an
// overlay without re-printing the whole lot to Serial again.
char lotBuf[LCD_ROWS][LCD_COLS + 1];

// ---------------------------------------------------------------------------
// FULL TEXT ON THE GLASS  (replaces spoken playback)
// There is no separate playback area. Bringing a loaded car
// back to the speaker no longer says anything out loud — it puts the WHOLE
// task on the screen and pages through it. The board owns the screen; the 18
// character label is only what fits on one line of the lot.
// The laptop sends it in chunks because the AVR RX buffer is 64 bytes:
//   FULLCLR            start a new one
//   FULL <chunk>       append (keep chunks <= 40 chars)
//   FULLSHOW <n>       wrap it and show it for car n
// ---------------------------------------------------------------------------
#define FULL_LEN   120
#define WRAP_LINES 9            // 3 pages of 3 rows
char fullText[FULL_LEN + 1];
byte fullLen   = 0;
char wrapLine[WRAP_LINES][LCD_COLS + 1];
byte wrapCount = 0;
byte fullPage  = 0;
unsigned long fullPageAt = 0;
const unsigned long PAGE_MS = 2500;   // long enough to actually read a line
const unsigned long PLAY_MS = 12000;  // YOUR ORDER drops back to the lot on its
                                      // own. Without this it stuck forever
                                      // unless a car happened to park.
unsigned long playUntil = 0;

// Break the text into <= LCD_COLS chunks, preferring to break at a space.
void wrapFull() {
  wrapCount = 0;
  byte i = 0;
  while (fullText[i] && wrapCount < WRAP_LINES) {
    byte take = 0, lastSpace = 0;
    while (take < LCD_COLS && fullText[i + take]) {
      if (fullText[i + take] == ' ') lastSpace = take;
      take++;
    }
    if (fullText[i + take] && lastSpace) take = lastSpace;   // break on a word
    byte j = 0;
    for (; j < take; j++) wrapLine[wrapCount][j] = fullText[i + j];
    wrapLine[wrapCount][j] = '\0';
    wrapCount++;
    i += take;
    while (fullText[i] == ' ') i++;                          // eat the space
  }
}

// Forward declarations — the screen painter is defined further down, next to the
// rest of the LCD code, but loop() and printLot() above it both need it.
void paintScreen();
void tickScreen();
void announceOrderIn();
void announceAllDone();
void announce(const char* msg);
void centreRow(byte row, const char* text);

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

  // SIX devices on one SPI bus. PCD_Init() drives its own SS pin HIGH, but it
  // does that one reader at a time - so while rfid1 is initialising, the five
  // SS pins that have not been touched yet are still floating INPUTs and any
  // one of them can read as selected. With four readers that was survivable.
  // With six it is the classic way a bus goes quiet, so deselect all six FIRST
  // and let PCD_Init() find them already parked HIGH.
  const byte allSS[6] = { SS_PIN1, SS_PIN2, SS_PIN3, SS_PIN4, SS_SPEAKER, SS_PICKUP };
  for (byte i = 0; i < 6; i++) { pinMode(allSS[i], OUTPUT); digitalWrite(allSS[i], HIGH); }

  SPI.begin();
  Wire.begin();

  for (byte c = 0; c < MAX_CARS; c++) taskOf[c][0] = '\0';
  for (byte r = 0; r < LCD_ROWS; r++) shown[r][0] = '\0';

  rfid1.PCD_Init();
  rfid2.PCD_Init();
  rfid3.PCD_Init();
  rfid4.PCD_Init();
  rfidSpeaker.PCD_Init();
  rfidPickup.PCD_Init();

  Serial.println();
  Serial.println(F("=== TaskLot v2 - four spaces, a speaker, a pickup lane ==="));

  // Boot check. 0x91/0x92 = genuine, 0x88/0x12 = clone (fine),
  // 0x00 or 0xFF = that reader is not talking. Find out here, not mid-demo.
  for (byte s = 0; s < NUM_SPACES; s++) {
    occupant[s] = -1;
    lastSeen[s] = 0;

    Serial.print(F("space "));
    Serial.print(s + 1);
    reportVersion(space[s], SS_PINS_space(s));
  }
  for (byte l = 0; l < NUM_LANES; l++) {
    lastLaneCar[l] = -1;
    lastLaneAt[l]  = 0;

    Serial.print(l == LANE_SPEAKER ? F("speaker") : F("pickup "));
    reportVersion(lane[l], l == LANE_SPEAKER ? SS_SPEAKER : SS_PICKUP);
  }
  Serial.println(F("(good versions but no tag reads = starved 3.3V rail, not wiring)"));

  startLcd();
  loadAll();

  Serial.println(F("Drive past the SPEAKER to order. PARK to finish the order."));
  Serial.println(F("Drive through PICKUP when the task is done."));
  Serial.println(F("Send: CAR <n> <text> | DONE <n> | CLEAR | LOT | PING"));
  Serial.println();
  printLot();
}

// Which SS pin a space index sits on - boot-message dressing only.
byte SS_PINS_space(byte s) {
  const byte p[NUM_SPACES] = { SS_PIN1, SS_PIN2, SS_PIN3, SS_PIN4 };
  return p[s];
}

void reportVersion(MFRC522* r, byte ssPin) {
  byte v = r->PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print(F(" reader (SS "));
  Serial.print(ssPin);
  Serial.print(F("): 0x"));
  if (v < 0x10) Serial.print('0');
  Serial.print(v, HEX);
  if (v == 0x00 || v == 0xFF)      Serial.println(F("   <-- NOT TALKING"));
  else if (v == 0x91 || v == 0x92) Serial.println(F("   ok - genuine"));
  else if (v == 0x88 || v == 0x12) Serial.println(F("   ok - clone"));
  else                             Serial.println(F("   ?? unexpected, but answering"));
}

void loop() {
  readCommands();                       // the laptop talks first - it's cheap

  // Spaces first, in the verified order. The lanes go last so that a car being
  // carried out of a space is registered as gone before the lane sees it.
  for (byte s = 0; s < NUM_SPACES; s++) {
#if USE_PRESENCE
    if (occupant[s] < 0) checkArrival(s);
    else                 checkStillThere(s);
#else
    checkArrival(s);
#endif
  }

  checkLane(LANE_SPEAKER);
  checkLane(LANE_PICKUP);

  delay(60);   // let the shared bus breathe between readers
  tickScreen();      // flash the overlays; never blocks readCommands()
}

// ===========================================================================
// The LCD   -- copied from tasklot_full / lcd_bridge, unchanged
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

// Centre a short string on a 20-column row.
void centreRow(byte row, const char* text) {
  char line[LCD_COLS + 1];
  byte n = 0;
  while (text[n] && n < LCD_COLS) n++;
  byte pad = (LCD_COLS - n) / 2;
  byte i = 0;
  for (; i < pad; i++) line[i] = ' ';
  for (byte j = 0; j < n; j++) line[i++] = text[j];
  line[i] = '\0';
  lcdRow(row, line);
}

// ===========================================================================
// paintScreen() — the ONLY thing that decides what is on the glass.
//
// Everything else sets state and lets this draw it. That is why an overlay can
// expire mid-command without anything else needing to know.
// ===========================================================================
void paintScreen() {
  char line[LCD_COLS + 1];

  switch (overlay) {

    // --- talking at the speaker. The banner flashes; the rest stays put, so it
    // --- reads as an active indicator rather than a screen that is broken.
    case OV_ORDERING:
      centreRow(0, flashOn ? "ORDER IN PROGRESS" : "");
      strcpy(line, "CAR ");
      line[4] = '1' + ordering;
      line[5] = '\0';
      centreRow(1, line);
      centreRow(2, "listening...");
      centreRow(3, "park it when done");
      return;

    // --- a receipt for something that just happened: ORDER IS IN after a task is
    // --- recorded, ALL DONE!! when one is collected. The WHOLE screen flashes,
    // --- fast, then the lot comes back with the change already made behind it.
    case OV_ANNOUNCE:
      centreRow(0, "");
      centreRow(1, flashOn ? announceMsg : "");
      centreRow(2, "");
      centreRow(3, "");
      return;

    // --- the speaker reading a task back
    case OV_PLAYING:
      centreRow(0, "YOUR ORDER");
      if (wrapCount) {
        // The whole task, left-aligned so it reads as text, paged if long.
        for (byte r = 0; r < 3; r++) {
          byte idx = fullPage * 3 + r;
          lcdRow(r + 1, idx < wrapCount ? wrapLine[idx] : "");
        }
      } else if (taskOf[playing][0]) {
        byte i = 0;
        for (; i < LCD_COLS && taskOf[playing][i]; i++) line[i] = taskOf[playing][i];
        line[i] = '\0';
        centreRow(1, line);
        centreRow(2, "");
        centreRow(3, "");
      } else {
        centreRow(1, "(no task)");
        centreRow(2, "");
        centreRow(3, "");
      }
      return;

    // --- the lot. THIS IS THE PRIORITY LIST.
    default:
      for (byte r = 0; r < LCD_ROWS; r++) lcdRow(r, lotBuf[r]);
      return;
  }
}

// Called every loop. Advances the flash phase and expires OV_ORDER_IN.
// Costs nothing when no overlay is up.
void tickScreen() {
  if (overlay == OV_NONE) return;

  unsigned long now = millis();

  // A long task pages itself. Nothing flashes here — it is text to be read.
  if (overlay == OV_PLAYING) {
    if (playUntil && (long)(now - playUntil) >= 0) {
      overlay  = OV_NONE;
      playing  = -1;
      playUntil = 0;
      paintScreen();                   // back to the lot, by itself
      return;
    }
    if (wrapCount > 3 && now - fullPageAt >= PAGE_MS) {
      fullPageAt = now;
      byte pages = (wrapCount + 2) / 3;
      fullPage   = (fullPage + 1) % pages;
      paintScreen();
    }
    return;
  }

  if (overlay == OV_ANNOUNCE && (long)(now - overlayUntil) >= 0) {
    overlay = OV_NONE;                 // the announcement is over
    flashOn = true;
    paintScreen();                     // ...and the reorganised lot appears
    return;
  }

  unsigned long period = (overlay == OV_ANNOUNCE) ? FLASH_FAST_MS : FLASH_SLOW_MS;
  if (now - flashAt >= period) {
    flashAt = now;
    flashOn = !flashOn;
    paintScreen();
  }
}

// Flash a receipt over the lot. The lot is already rendered into lotBuf and
// already sent to Serial by the time this runs — ONLY THE GLASS WAITS, which is
// what keeps serial pacing intact.
//   ORDER IS IN   a task was just recorded onto a car
//   ALL DONE!!    a task was just collected and the car is blank again
void announce(const char* msg) {
  announceMsg  = msg;
  overlay      = OV_ANNOUNCE;
  overlayUntil = millis() + ANNOUNCE_MS;
  flashAt      = millis();
  flashOn      = true;
  paintScreen();
}

void announceOrderIn() { announce("ORDER IS IN"); }
void announceAllDone() { announce("ALL DONE!!"); }


// Always prints to Serial (the live page and the simulator parse it, and the two
// rule lines are what paces the sender). The GLASS is left to paintScreen(),
// which may be showing an overlay instead.
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
    strcpy(lotBuf[s], line);                  // keep it for repaints
  }
  Serial.println(F("--------------------"));

  paintScreen();
}

// ===========================================================================
// Commands from the laptop   -- unchanged from tasklot_full
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

void speakerPass(int car);   // defined below with the lane readers

void runCommand(char* line) {
  if (strncmp(line, "PING", 4) == 0) { Serial.println(F("PONG")); return; }

  // LOT means "show me the lot", so it is also how a read-back ends - the page
  // sends it when the laptop's voice stops.
  if (strncmp(line, "LOT", 3) == 0) {
    playing = -1;
    if (overlay == OV_PLAYING) overlay = OV_NONE;
    printLot();
    return;
  }

  if (strncmp(line, "FORGET", 6) == 0) { forgetAll(); return; }

  // ORDER <n> - the SPEAKER READER is the real source of this on the finished
  // build, so the board does not need to be told. It is accepted anyway for one
  // reason: tools/sim drives a board over Web Serial and sends ORDER when a car
  // is dragged onto the speaker. Without this, the simulator silently stops
  // being able to drive v2 - which is exactly the fallback you want working when
  // a reader goes quiet five minutes before a review.
  //
  // It goes through the same speakerPass() the reader calls, so there is one
  // code path and the two cannot drift.
  if (strncmp(line, "ORDER ", 6) == 0) {
    int n = atoi(line + 6);
    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    speakerPass(n - 1);
    return;
  }

  // PLAY <n> - same reasoning as ORDER above: the speaker reader is the real
  // source, but tools/sim needs to be able to drive a read-back over Web Serial.
  if (strncmp(line, "PLAY ", 5) == 0) {
    int n = atoi(line + 5);
    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    ordering = -1;
    playing  = n - 1;
    overlay  = OV_PLAYING;
    printLot();
    return;
  }

  if (strncmp(line, "FULLCLR", 7) == 0) { fullLen = 0; fullText[0] = '\0'; return; }

  if (strncmp(line, "FULLSHOW ", 9) == 0) {
    int n = atoi(line + 9);
    if (n < 1 || n > MAX_CARS) { Serial.print(F("* bad car number: ")); Serial.println(n); return; }
    wrapFull();
    ordering   = -1;
    playing    = n - 1;
    fullPage   = 0;
    fullPageAt = millis();
    playUntil  = millis() + PLAY_MS;
    overlay    = OV_PLAYING;
    printLot();
    return;
  }

  if (strncmp(line, "FULL ", 5) == 0) {
    const char* src = line + 5;
    if (fullLen && fullLen < FULL_LEN) fullText[fullLen++] = ' ';
    while (*src && fullLen < FULL_LEN) fullText[fullLen++] = *src++;
    fullText[fullLen] = '\0';
    return;
  }

  if (strncmp(line, "CLEAR", 5) == 0) {
    for (byte c = 0; c < MAX_CARS; c++) { taskOf[c][0] = '\0'; saveCar(c); }
    fullLen = 0; fullText[0] = '\0'; wrapCount = 0;
    Serial.println(F("* tasks cleared"));
    printLot();
    return;
  }

  // DONE <n> - the task is finished, so the car goes back to being a blank key.
  // The pickup lane does this from the hardware side now; this stays as the
  // laptop's override.
  if (strncmp(line, "DONE ", 5) == 0) {
    int n = atoi(line + 5);
    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    bool had = taskOf[n - 1][0] != '\0';
    blankTask((byte)(n - 1));
    playing = -1; ordering = -1;
    printLot();
    if (had) announceAllDone();
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

// Wipe one car's label and echo it, in the same shape as any other label change,
// so the page updates the same way whether the laptop or the pickup lane did it.
void blankTask(byte c) {
  taskOf[c][0] = '\0';
  saveCar(c);
  Serial.print(F("TASK "));
  Serial.print(c + 1);
  Serial.println(' ');
}

// ===========================================================================
// Readers - the SPACES. Unchanged from the verified sketch.
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

  // PARKING IS THE STOP GESTURE. Whoever was ordering, the order is over the
  // moment a car comes to rest - which is why there is no stop button. Note it
  // BEFORE the early-out below: a car re-landing on the space it already held
  // still owes the screen a redraw back to the lot.
  // ** WAS A TASK ACTUALLY JUST RECORDED? ** speakerPass() only opens an order for
  // a BLANK car, so "an order was open" IS the test for first-time. Moving an
  // already-loaded car between spaces reorders silently, with no announcement.
  bool orderJustClosed = (ordering >= 0);
  bool wasOrdering = (ordering >= 0 || playing >= 0);
  playing = -1;                     // parking also cuts a read-back short
  if (!orderJustClosed) overlay = OV_NONE;
  ordering = -1;

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
    printLot();                    // Serial + lotBuf, unconditionally
  } else if (wasOrdering) {
    printLot();       // nothing moved, but the order just closed - show the lot
  }

  // ...and if a task was just recorded, the glass says ORDER IS IN first. The
  // lot is already rendered underneath; it appears when the announcement expires.
  if (orderJustClosed) announceOrderIn();
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
// Readers - the LANES. Arrival detection only, plus a debounce.
//
// Same MFRC522 call sequence as a space arrival - IsNewCardPresent, then
// ReadCardSerial, then HaltA and StopCrypto1 - because that sequence is the
// part that is proven. What is different is everything AFTER the read: a lane
// never writes occupant[], never touches lastSeen[], never calls WakeupA, and
// never shows up on the four-line lot.
// ===========================================================================
void checkLane(byte l) {
  MFRC522 &rfid = *lane[l];

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

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  // ONE PASS = ONE EVENT. A car left lying on the reader would otherwise
  // re-trigger every 60 ms. Same car, still inside the cooldown -> same pass,
  // already handled, drop it. A different car is always a new event.
  unsigned long now = millis();
  if (lastLaneCar[l] == car && (now - lastLaneAt[l]) < LANE_COOLDOWN_MS) {
    lastLaneAt[l] = now;    // keep sliding while it lingers, so lifting it off
    return;                 // and putting it back is what re-arms the lane
  }
  lastLaneCar[l] = car;
  lastLaneAt[l]  = now;

  if (l == LANE_SPEAKER) speakerPass(car);
  else                   pickupPass(car);
}

// THE SPEAKER. Driving past it places an order: the laptop starts recording and
// the screen belongs to the order until the car parks. One speaker, one car at a
// time - a second car simply replaces the first, same as lcd_bridge.
// THE SPEAKER - one reader, two jobs, and the CAR decides which.
//
//   blank car  -> you are ORDERING. The laptop starts recording; parking ends it.
//   loaded car -> the speaker READS IT BACK to you, in full, and names the first
//                 move to make. The board only shows the screen: it holds 18
//                 characters, and the laptop holds the sentence you actually said.
//
// This is what a real drive-through speaker does, so nobody has to be told which
// mode they are in - the car in your hand already says.
void speakerPass(int car) {
  if (taskOf[car][0]) {
    Serial.print(F("PLAYBACK CAR "));
    Serial.print(car + 1);
    Serial.println(F(" reading back"));
    ordering = -1;
    playing  = car;
    // The laptop needs ~1s to send the full text. Drop the PREVIOUS car's
    // wrapped lines now, so this shows THIS car's own 18-char label first and
    // upgrades to the full text when it arrives -- instead of briefly showing
    // somebody else's task.
    wrapCount  = 0;
    fullLen    = 0;
    fullText[0] = '\0';
    fullPage   = 0;
    playUntil  = millis() + PLAY_MS;
    overlay    = OV_PLAYING;
    printLot();
    return;
  }

  Serial.print(F("SPEAKER  CAR "));
  Serial.print(car + 1);
  Serial.println(F(" ordering"));

  ordering = car;
  playing  = -1;
  overlay  = OV_ORDERING;        // "ORDER IN PROGRESS", flashing
  flashAt  = millis();
  flashOn  = true;
  printLot();
}

// THE PICKUP LANE. The order is collected: blank the label, because the car is a
// KEY, not a container - once the task is done the key is empty and ready to be
// ordered onto again.
//
// This is the gesture v1 did not have. A quiet space still means nothing; a read
// here is a person physically saying "this one is finished."
void pickupPass(int car) {
  Serial.print(F("PICKUP   CAR "));
  Serial.print(car + 1);
  Serial.println(F(" collected"));

  // Collecting a car that was never given a task is not an error - it is a car
  // being carried around. Report it, blank nothing that isn't there, move on -
  // and give no receipt, because nothing was actually finished.
  bool had = taskOf[car][0] != '\0';
  blankTask((byte)car);

  // The car has physically left the lot, so release whatever space it held.
  // Presence tracking would notice this in GONE_MS anyway, but doing it here
  // makes the screen update on the gesture instead of a beat later - and keeps
  // the pickup lane working with USE_PRESENCE 0, where nothing would ever
  // notice the space went quiet.
  for (byte o = 0; o < NUM_SPACES; o++) {
    if (occupant[o] == car) {
      Serial.print(F("SPACE "));
      Serial.print(o + 1);
      Serial.print(F("  -> CAR "));
      Serial.print(car + 1);
      Serial.println(F(" left"));
      occupant[o] = -1;
    }
  }

  // If the car being collected is the one that is mid-order, that order can
  // never be parked closed - so let the pickup close it. This is the ONLY other
  // way an order ends, and it exists to stop the screen sticking on ORDER UP,
  // not as a stop button: it takes the same car through a different lane.
  if (ordering == car) ordering = -1;
  if (playing  == car) playing  = -1;
  overlay = OV_NONE;

  printLot();                      // Serial + lotBuf, unconditionally
  if (had) announceAllDone();      // ...and the glass says ALL DONE!! first
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

// A UID whose tail is all zeros is a READ THAT DIED HALFWAY, not a new car.
// Seen twice on the bench: 04 D1 60 00 00 00 00 and 04 E1 63 00 00 00 00, both
// partial reads of real cars whose UIDs start with the same two bytes. The
// board registered them as new cars, and a new car has no task, so the speaker
// started recording instead of showing the task. Starved 3.3V rail is the
// underlying cause (six RC522s on a 50 mA rail); this stops the symptom.
bool plausibleUID(MFRC522 &rfid) {
  if (rfid.uid.size < 4) return false;
  byte zeros = 0;
  for (byte b = 0; b < rfid.uid.size; b++) if (rfid.uid.uidByte[b] == 0) zeros++;
  if (zeros >= 3) return false;                 // NTAG213 UIDs are not mostly zero
  // trailing run of zeros = truncated read
  if (rfid.uid.uidByte[rfid.uid.size - 1] == 0 &&
      rfid.uid.uidByte[rfid.uid.size - 2] == 0) return false;
  return true;
}

// A brand-new UID must be seen TWICE IN A ROW, identically, before it earns a
// car slot. A known car still registers on one read, so nothing gets slower.
byte pendingUID[10];
byte pendingLen = 0;

bool confirmedTwice(MFRC522 &rfid) {
  bool same = (pendingLen == rfid.uid.size);
  if (same) {
    for (byte b = 0; b < pendingLen; b++) {
      if (pendingUID[b] != rfid.uid.uidByte[b]) { same = false; break; }
    }
  }
  if (same) { pendingLen = 0; return true; }    // second identical sighting
  pendingLen = rfid.uid.size;                   // remember it and wait
  for (byte b = 0; b < rfid.uid.size; b++) pendingUID[b] = rfid.uid.uidByte[b];
  return false;
}

// Remember a UID we've never seen before
int addCar(MFRC522 &rfid) {
  if (carCount >= MAX_CARS) return -1;
  if (!plausibleUID(rfid)) {
    Serial.print(F("* ignored a bad read (truncated UID): "));
    printUID(rfid);
    Serial.println();
    return -1;
  }
  // NOTE: a "must be seen twice" rule was tried here and reverted 8/27 -- the
  // reader halts a card after reading it, so a resting car is never re-polled
  // and NOTHING registered until you tapped each car twice. The zero-tail check
  // above is what actually catches the phantoms, and it costs nothing.
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
