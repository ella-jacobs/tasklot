// lcd_bridge - the LCD half of tasklot_full, with the laptop standing in for the
// readers.  [RUNS ON THE UNO. Also runs on the Mega.]
//
// WHY THIS EXISTS
//
// The four RC522s are not wired to a board yet, but the LCD works. Everything in
// tasklot_full that is NOT a reader - the screen, the priority list, the task
// text, the serial command set - can be proven on hardware right now, on the UNO,
// with the laptop sending the events a reader would have sent.
//
// ** EVERY SHARED FUNCTION IS COPIED FROM tasklot_full VERBATIM. ** startLcd(),
// lcdRow(), printLot(), readCommands(), and the CAR/DONE/CLEAR/LOT/PING branches
// of runCommand() are the same code. So when this sketch renders correctly on the
// glass, that half of tasklot_full is bench-proven. Only the reader half stays
// unknown.
//
// What is REMOVED: SPI, MFRC522, the UID->car table, EEPROM. Nothing here needs
// them, and the UNO does not have the Mega's pins for the readers anyway.
//
// What is ADDED: two commands that do what a reader does.
//      PARK <space> <car>    a car is now sitting on that space
//      LEAVE <space>         that space went quiet
// They print the SAME two lines the readers print, word for word, so
// tasklot-live.html and tools/sim parse this board exactly like the real one.
//
// ---------------------------------------------------------------------------
// WIRING - LCD2004A + I2C backpack
//
//   UNO :  VCC -> 5V   GND -> GND   SDA -> A4   SCL -> A5
//   MEGA:  VCC -> 5V   GND -> GND   SDA -> 20   SCL -> 21
//
// Wire.begin() takes no pins, so this file is the same on both boards - the I2C
// pins are fixed in hardware and differ only in where they are printed.
//
// ** THE LCD WANTS 5V. ** The readers want 3.3V. Never reuse a reader wire here.
// ** SET THE CONTRAST POT. ** Backlight on but no letters = contrast, not a dead
// screen.
//
// ---------------------------------------------------------------------------
// WHAT THE LAPTOP CAN SEND (9600 baud, one command per line)
//
//   PLAY <n>         car n pulled up to the SPEAKER carrying a task, so the speaker
//                    is reading it back. The board shows the read-back screen; the
//                    LAPTOP does the talking (it has the full sentence; the board
//                    only has 18 characters). `LOT` ends it.
//   ORDER <n>        car n just drove past the SPEAKER BLANK - it is placing an order.
//                    The screen flashes ORDER IN PROGRESS until the car parks.
//                    The laptop starts recording; the screen says so. The order
//                    ends when the car parks, so there is no stop command and no
//                    stop button: PARK is the stop gesture.
//   PARK <s> <n>     car n is parked on space s (1-4). Parking a car releases
//                    whatever space it was on before, so moving a car REORDERS
//                    the list instead of appearing twice. Same rule as the board.
//                    Parking ALSO ends an open order, whoever placed it.
//   LEAVE <s>        space s is empty now.
//   EMPTY            every space goes quiet. (Cars keep their task text.)
//
//   CAR <n> <text>   set car n's LCD line. Truncated to 18 chars.
//   DONE <n>         car n reached the PICKUP LANE: the task is finished, so blank
//                    its label. The screen flashes ALL DONE!! first. The car is a KEY, not a container - once the order
//                    is picked up the key is empty and ready to order again.
//   CLEAR            forget every task label.
//   LOT              reprint the lot.
//   PING             -> PONG
//
// Only one program can hold the port at a time. Close the Serial Monitor before
// running the simulator or tasklot-live.html against this.
//
// AI disclosure: written with Claude (Anthropic) to Ella's design, by lifting the
// shared half of tasklot_full. LiquidCrystal_I2C is Frank de Brabander's.
// Credit all of it in the critique.

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const byte NUM_SPACES = 4;
const byte MAX_CARS   = 8;

// ---- the task text, one line per car. 18 chars because "1>" eats two of the
// ---- twenty. The laptop does the shortening; the board just stores what it's told.
const byte LCD_COLS = 20;
const byte LCD_ROWS = 4;
const byte TASK_LEN = 18;
char taskOf[MAX_CARS][TASK_LEN + 1];

// ---- what each space is holding right now. -1 = empty. Same shape as the board.
int occupant[NUM_SPACES];

// ---- an order in progress. -1 = nobody is at the speaker.
// The lot is not shown while an order is open; the screen belongs to the order,
// which is what makes driving past the speaker a visible event from across a room.
int ordering = -1;

// ---- a read-back in progress. -1 = nothing is playing.
// THE SPEAKER HAS TWO JOBS and the CAR decides which: a blank car is ordering, a
// car that already carries a task is having it read back. Same as a real
// drive-through speaker, which takes your order and then repeats it to you.
// The board only owns the SCREEN for this - the laptop holds the full text and
// does the talking, because 18 characters is a label, not a sentence.
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

// ---- the LCD ----
LiquidCrystal_I2C lcd(0x27, LCD_COLS, LCD_ROWS);
byte lcdAddress = 0;                 // 0 = no screen; the sketch runs anyway
char shown[LCD_ROWS][LCD_COLS + 1];  // what's physically on the glass right now

// ---- inbound command buffer ----
char cmd[48];
byte cmdLen = 0;

// ===========================================================================
void setup() {
  Serial.begin(9600);
  Wire.begin();

  for (byte c = 0; c < MAX_CARS; c++)  taskOf[c][0] = '\0';
  for (byte r = 0; r < LCD_ROWS; r++)  shown[r][0]  = '\0';
  for (byte s = 0; s < NUM_SPACES; s++) occupant[s] = -1;

  Serial.println();
  Serial.println(F("=== TaskLot - LCD bridge (no readers; the laptop parks) ==="));

  startLcd();

  Serial.println(F("Send: ORDER <n> | PARK <s> <n> | LEAVE <s> | EMPTY"));
  Serial.println(F("      CAR <n> <text> | DONE <n> | CLEAR | LOT | PING"));
  Serial.println();
  printLot();
}

void loop() {
  readCommands();      // never blocked by the screen - that is the whole design
  tickScreen();
  delay(10);
}

// ===========================================================================
// The LCD   -- copied from tasklot_full, unchanged
// ===========================================================================

// The backpack is 0x27 or 0x3F and there is no way to tell by looking, so scan.
// If nothing answers, say so once and carry on.
void startLcd() {
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0 && (a == 0x27 || a == 0x3F)) { lcdAddress = a; break; }
  }
  if (!lcdAddress) {
    Serial.println(F("LCD: none found. Check 5V, GND, and SDA/SCL."));
    Serial.println(F("     The lot still prints to Serial."));
    return;
  }
  Serial.print(F("LCD: 0x"));
  Serial.println(lcdAddress, HEX);

  lcd = LiquidCrystal_I2C(lcdAddress, LCD_COLS, LCD_ROWS);
  lcd.init();
  lcd.backlight();
  lcd.clear();
}

// Write one row, but only if it actually changed. I2C is slow; blind rewrites
// make the screen flicker. Padded to full width - a short write leaves the tail
// of the previous line sitting on the glass.
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
// Copied from tasklot_full, unchanged.
// ===========================================================================
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
      if (taskOf[playing][0]) {
        byte i = 0;
        for (; i < LCD_COLS && taskOf[playing][i]; i++) line[i] = taskOf[playing][i];
        line[i] = '\0';
        centreRow(1, line);
      } else {
        centreRow(1, "(no task)");
      }
      strcpy(line, "CAR ");
      line[4] = '1' + playing;
      line[5] = '\0';
      centreRow(2, line);
      centreRow(3, "...listen up");
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
  if (overlay == OV_NONE || overlay == OV_PLAYING) return;

  unsigned long now = millis();

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

// ===========================================================================
// The lot, top space first. THIS IS THE PRIORITY LIST.
//
// Space order is priority order - space 1 is line 1 - so moving a car between
// spaces is how you reorder the list. That is the whole tangible interface:
// there is no sort button, you pick the car up.
//
// Always prints to Serial (the live page and the simulator parse it, and the
// two rule lines are what paces the sender). The GLASS is left to paintScreen(),
// which may be showing an overlay instead.
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
// The two lines the readers print. Word for word what tasklot_full sends, so
// the live page and the simulator parse this board identically.
// ===========================================================================
void sayParked(byte s, byte car) {
  Serial.print(F("SPACE "));
  Serial.print(s + 1);
  Serial.print(F("  <- CAR "));
  Serial.print(car + 1);
  Serial.println(F(" parked"));
}

void sayLeft(byte s, byte car) {
  Serial.print(F("SPACE "));
  Serial.print(s + 1);
  Serial.print(F("  -> CAR "));
  Serial.print(car + 1);
  Serial.println(F(" left"));
}

// ===========================================================================
// Commands from the laptop   -- reader from tasklot_full, unchanged
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
  }
}

// Step over one run of digits and the spaces after it.
char* afterNumber(char* p) {
  while (*p && *p != ' ') p++;
  while (*p == ' ') p++;
  return p;
}

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

  // ---- the reader stand-ins -------------------------------------------------

  // PLAY <car> - a loaded car pulled up to the speaker; it is being read back.
  if (strncmp(line, "PLAY ", 5) == 0) {
    int n = atoi(line + 5);
    if (n < 1 || n > MAX_CARS) { Serial.print(F("* bad car number: ")); Serial.println(n); return; }
    ordering = -1;                             // a read-back interrupts an order
    playing  = n - 1;
    overlay  = OV_PLAYING;
    printLot();
    return;
  }

  // ORDER <car> - a BLANK car is at the speaker. The laptop starts recording.
  if (strncmp(line, "ORDER ", 6) == 0) {
    int n = atoi(line + 6);
    if (n < 1 || n > MAX_CARS) { Serial.print(F("* bad car number: ")); Serial.println(n); return; }
    ordering = n - 1;
    playing  = -1;
    overlay  = OV_ORDERING;                    // "ORDER IN PROGRESS", flashing
    flashAt  = millis();
    flashOn  = true;
    printLot();
    return;
  }

  // PARK <space> <car>
  if (strncmp(line, "PARK ", 5) == 0) {
    char* p = line + 5;
    while (*p == ' ') p++;
    int s = atoi(p);
    int n = atoi(afterNumber(p));

    if (s < 1 || s > NUM_SPACES) { Serial.print(F("* bad space: ")); Serial.println(s); return; }
    if (n < 1 || n > MAX_CARS)   { Serial.print(F("* bad car number: ")); Serial.println(n); return; }
    byte sp = s - 1, car = n - 1;

    // PARKING IS THE STOP GESTURE. Whoever was ordering, the order is over the
    // moment a car comes to rest - which is why there is no stop button.
    // ** WAS A TASK ACTUALLY JUST RECORDED? ** An order being open is exactly
    // that: the speaker only opens one for a BLANK car. So this is the test for
    // "first time" - moving an already-loaded car between spaces reorders
    // silently, with no announcement.
    bool orderJustClosed = (ordering >= 0);
    bool wasOverlaid     = (ordering >= 0 || playing >= 0);
    ordering = -1;
    playing  = -1;                             // parking also cuts a read-back short
    if (!orderJustClosed) overlay = OV_NONE;   // plain move: straight to the lot

    if (occupant[sp] == (int)car) {            // already there; nothing moved,
      if (wasOverlaid) {                       // but the screen still owes us the lot
        printLot();
        if (orderJustClosed) announceOrderIn();
      }
      return;
    }

    // One space per car. Parking a car releases whatever it was on before, so
    // moving a car REORDERS the list instead of showing up twice. This is the
    // rule tasklot_full enforces, and the whole reason the lot is a ranking.
    for (byte o = 0; o < NUM_SPACES; o++) {
      if (o != sp && occupant[o] == (int)car) {
        sayLeft(o, car);
        occupant[o] = -1;
      }
    }

    if (occupant[sp] >= 0) {                   // something else was on this space
      sayLeft(sp, (byte)occupant[sp]);
    }

    occupant[sp] = car;
    sayParked(sp, car);
    printLot();                                // Serial + lotBuf, unconditionally
    // ...and if a task was just recorded, the glass says so first. The lot is
    // already rendered underneath; it appears when the announcement expires.
    if (orderJustClosed) announceOrderIn();
    return;
  }

  // LEAVE <space>
  if (strncmp(line, "LEAVE ", 6) == 0) {
    int s = atoi(line + 6);
    if (s < 1 || s > NUM_SPACES) { Serial.print(F("* bad space: ")); Serial.println(s); return; }
    byte sp = s - 1;
    if (occupant[sp] < 0) return;              // already empty
    if (overlay == OV_ANNOUNCE) overlay = OV_NONE;
    sayLeft(sp, (byte)occupant[sp]);
    occupant[sp] = -1;
    printLot();
    return;
  }

  // EMPTY - every space goes quiet. Task text survives; the cars still hold them.
  if (strncmp(line, "EMPTY", 5) == 0) {
    for (byte s = 0; s < NUM_SPACES; s++) {
      if (occupant[s] < 0) continue;
      sayLeft(s, (byte)occupant[s]);
      occupant[s] = -1;
    }
    printLot();
    return;
  }

  // ---- task text  -- copied from tasklot_full, unchanged --------------------

  if (strncmp(line, "CLEAR", 5) == 0) {
    for (byte c = 0; c < MAX_CARS; c++) taskOf[c][0] = '\0';
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
    bool had = taskOf[n - 1][0] != '\0';
    taskOf[n - 1][0] = '\0';
    Serial.print(F("TASK "));      // echo an empty label, same shape as any other
    Serial.print(n);               // label change, so the page updates the same way
    Serial.println(' ');
    playing  = -1;
    ordering = -1;
    printLot();                    // Serial + lotBuf, unconditionally
    // A car that actually carried something gets a receipt. Collecting an empty
    // car is just a car being carried around - no announcement for that.
    if (had) announceAllDone();
    return;
  }

  // CAR <n> <text>
  if (strncmp(line, "CAR ", 4) == 0) {
    char* p = line + 4;
    while (*p == ' ') p++;
    int n = atoi(p);                       // 1-based car number
    p = afterNumber(p);

    if (n < 1 || n > MAX_CARS) {
      Serial.print(F("* bad car number: "));
      Serial.println(n);
      return;
    }
    byte c = n - 1;
    byte i = 0;
    for (; i < TASK_LEN && p[i]; i++) taskOf[c][i] = p[i];
    taskOf[c][i] = '\0';

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
