// LcdView.cpp - the screen painter and its timers. See LcdView.h.

#include "LcdView.h"

#include <Wire.h>

#include "timing.h"

namespace {
// Screen text. Plain literals: they are passed around as const char* and compared by
// the row cache, and the whole set is small.
const char* const TEXT_ORDERING = "ORDER IN PROGRESS";
const char* const TEXT_LISTENING = "listening...";
const char* const TEXT_PARK_HINT = "park it when done";
const char* const TEXT_YOUR_ORDER = "YOUR ORDER";
const char* const TEXT_NO_TASK = "(no task)";
const char* const TEXT_EMPTY = "";

// Row layout of the full-screen overlays.
const byte ROW_TITLE = 0;
const byte ROW_MAIN = 1;
const byte ROW_SUB = 2;
const byte ROW_HINT = 3;
}  // namespace

LcdView::LcdView(const CarRegistry& cars, const ReadbackText& text, const OrderState& order)
    : cars_(cars),
      text_(text),
      order_(order),
      lcd_(LCD_ADDR_A, LCD_COLS, LCD_ROWS),
      address_(0),
      overlay_(OV_NONE),
      announceMessage_(TEXT_EMPTY),
      announceUntil_(0),
      flashAt_(0),
      flashOn_(true),
      page_(0),
      pageAt_(0),
      playUntil_(0) {
  for (byte r = 0; r < LCD_ROWS; r++) {
    lotRows_[r][0] = '\0';
    shown_[r][0] = '\0';
  }
}

byte LcdView::begin() {
  for (byte a = I2C_FIRST_ADDR; a < I2C_END_ADDR; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0 && (a == LCD_ADDR_A || a == LCD_ADDR_B)) {
      address_ = a;
      break;
    }
  }
  if (!address_) return 0;

  lcd_ = LiquidCrystal_I2C(address_, LCD_COLS, LCD_ROWS);
  lcd_.init();
  lcd_.backlight();
  lcd_.clear();
  return address_;
}

LcdView::Overlay LcdView::overlay() const { return overlay_; }

void LcdView::setLotRow(byte row, const char* text) { strcpy(lotRows_[row], text); }

// ---------------------------------------------------------------------------
// Overlay requests. None of these draw; the caller prints the lot (which paints) or
// calls paint() itself, so the glass is drawn once per event.
// ---------------------------------------------------------------------------

void LcdView::showOrdering(uint32_t now) {
  overlay_ = OV_ORDERING;
  flashAt_ = now;
  flashOn_ = true;
}

void LcdView::resumeReadback() { overlay_ = OV_PLAYING; }

void LcdView::startReadback(uint32_t now) {
  page_ = 0;
  playUntil_ = now + PLAY_MS;
  overlay_ = OV_PLAYING;
}

void LcdView::startFullTextReadback(uint32_t now) {
  startReadback(now);
  pageAt_ = now;
}

void LcdView::closeReadback() {
  if (overlay_ == OV_PLAYING) overlay_ = OV_NONE;
}

void LcdView::closeOrderScreens() {
  if (overlay_ == OV_ORDERING || overlay_ == OV_PLAYING) overlay_ = OV_NONE;
}

void LcdView::closeOverlay() { overlay_ = OV_NONE; }

void LcdView::announce(const char* message, uint32_t now) {
  announceMessage_ = message;
  overlay_ = OV_ANNOUNCE;
  announceUntil_ = now + ANNOUNCE_MS;
  flashAt_ = now;
  flashOn_ = true;
  paint();
}

// ---------------------------------------------------------------------------
// Timers
// ---------------------------------------------------------------------------

bool LcdView::tick(uint32_t now) {
  if (overlay_ == OV_NONE) return false;

  // A read-back pages itself and nothing flashes: it is text to be read.
  if (overlay_ == OV_PLAYING) {
    if (playUntil_ && deadlineReached(now, playUntil_)) {
      overlay_ = OV_NONE;
      playUntil_ = 0;
      paint();
      return true;
    }
    byte rows = text_.rowCount();
    if (rows > READBACK_ROWS_PER_PAGE && elapsedMs(now, pageAt_) >= PAGE_MS) {
      pageAt_ = now;
      byte pages = (rows + READBACK_ROWS_PER_PAGE - 1) / READBACK_ROWS_PER_PAGE;
      page_ = (page_ + 1) % pages;
      paint();
    }
    return false;
  }

  if (overlay_ == OV_ANNOUNCE && deadlineReached(now, announceUntil_)) {
    overlay_ = OV_NONE;  // the announcement is over...
    flashOn_ = true;
    paint();             // ...and the updated lot appears
    return false;
  }

  uint32_t period = (overlay_ == OV_ANNOUNCE) ? FLASH_FAST_MS : FLASH_SLOW_MS;
  if (elapsedMs(now, flashAt_) >= period) {
    flashAt_ = now;
    flashOn_ = !flashOn_;
    paint();
  }
  return false;
}

// ---------------------------------------------------------------------------
// Painting
// ---------------------------------------------------------------------------

void LcdView::paint() {
  switch (overlay_) {
    case OV_ORDERING:
      paintOrdering();
      return;
    case OV_ANNOUNCE:
      paintAnnouncement();
      return;
    case OV_PLAYING:
      paintReadback();
      return;
    case OV_NONE:
    default:
      // The lot. This is the priority list.
      for (byte r = 0; r < LCD_ROWS; r++) writeRow(r, lotRows_[r]);
      return;
  }
}

// Only the banner flashes; the rest stays put, so it reads as an active indicator
// rather than a screen that is broken.
void LcdView::paintOrdering() {
  char line[LCD_COLS + 1];
  centreRow(ROW_TITLE, flashOn_ ? TEXT_ORDERING : TEXT_EMPTY);
  strcpy(line, "CAR ");
  line[4] = static_cast<char>('1' + order_.ordering);
  line[5] = '\0';
  centreRow(ROW_MAIN, line);
  centreRow(ROW_SUB, TEXT_LISTENING);
  centreRow(ROW_HINT, TEXT_PARK_HINT);
}

// A receipt for something that just happened. The whole screen flashes, fast, then the
// lot comes back with the change already made behind it.
void LcdView::paintAnnouncement() {
  centreRow(ROW_TITLE, TEXT_EMPTY);
  centreRow(ROW_MAIN, flashOn_ ? announceMessage_ : TEXT_EMPTY);
  centreRow(ROW_SUB, TEXT_EMPTY);
  centreRow(ROW_HINT, TEXT_EMPTY);
}

// The whole task when the laptop has sent it (left-aligned, paged), otherwise the
// 18-character label so the screen is never blank while the full text is on its way.
void LcdView::paintReadback() {
  centreRow(ROW_TITLE, TEXT_YOUR_ORDER);

  byte rows = text_.rowCount();
  if (rows) {
    for (byte r = 0; r < READBACK_ROWS_PER_PAGE; r++) {
      byte index = page_ * READBACK_ROWS_PER_PAGE + r;
      writeRow(ROW_MAIN + r, index < rows ? text_.row(index) : TEXT_EMPTY);
    }
    return;
  }

  // NO_CAR is guarded so a stale state can never index the label table at -1.
  bool labelled = order_.playing != NO_CAR && cars_.hasLabel(order_.playing);
  centreRow(ROW_MAIN, labelled ? cars_.label(order_.playing) : TEXT_NO_TASK);
  centreRow(ROW_SUB, TEXT_EMPTY);
  centreRow(ROW_HINT, TEXT_EMPTY);
}

// Writes one row, padded to the full width (a short write would leave the tail of the
// previous text on the glass), and only if it changed: I2C is slow and this runs on
// every event, and blind rewrites make the screen flicker.
void LcdView::writeRow(byte row, const char* text) {
  char line[LCD_COLS + 1];
  byte i = 0;
  for (; i < LCD_COLS && text[i]; i++) line[i] = text[i];
  for (; i < LCD_COLS; i++) line[i] = ' ';
  line[LCD_COLS] = '\0';

  if (strcmp(line, shown_[row]) == 0) return;
  strcpy(shown_[row], line);
  if (!address_) return;
  lcd_.setCursor(0, row);
  lcd_.print(line);
}

void LcdView::centreRow(byte row, const char* text) {
  char line[LCD_COLS + 1];
  byte n = 0;
  while (text[n] && n < LCD_COLS) n++;
  byte pad = (LCD_COLS - n) / 2;
  byte i = 0;
  for (; i < pad; i++) line[i] = ' ';
  for (byte j = 0; j < n; j++) line[i++] = text[j];
  line[i] = '\0';
  writeRow(row, line);
}
