// LcdView.h - everything on the 20 x 4 LCD: the lot, the overlays, flashing, paging.
//
// Role: the only code that draws. Everything else sets state (OrderState, the lot rows,
// an overlay request) and LcdView decides what is on the glass, which is why an
// overlay can expire mid-command without anything else needing to know.
//
// Overlays:
//   ORDERING   "ORDER IN PROGRESS" flashing every FLASH_SLOW_MS while a car orders
//   ANNOUNCE   "ORDER IS IN" / "ALL DONE!!" flashing every FLASH_FAST_MS for ANNOUNCE_MS
//   PLAYING    "YOUR ORDER" with the task, paged every PAGE_MS, optional PLAY_MS timeout
//
// Nothing here uses delay(). The serial receive buffer is 64 bytes and the laptop keeps
// talking while the screen is busy; a blocking flash would drop bytes and merge
// commands. So every overlay is state plus a timestamp, advanced by tick() from loop().
// Serial output is never held back; only the glass waits.
//
// A missing LCD is not an error: rows are still tracked, nothing is sent to I2C, and
// the readers keep working.

#ifndef TASKLOT_LCD_VIEW_H
#define TASKLOT_LCD_VIEW_H

#include <LiquidCrystal_I2C.h>

#include "CarRegistry.h"
#include "OrderState.h"
#include "ReadbackText.h"
#include "config.h"

class LcdView {
 public:
  /** What covers the lot right now. */
  enum Overlay : byte { OV_NONE, OV_ORDERING, OV_PLAYING, OV_ANNOUNCE };

  /**
   * Params: cars - labels for the read-back; text - read-back rows; order - which car
   *   is ordering / playing. All three are read at paint time, never copied.
   */
  LcdView(const CarRegistry& cars, const ReadbackText& text, const OrderState& order);

  /**
   * Finds the LCD backpack on I2C (LCD_ADDR_A or LCD_ADDR_B) and initialises it.
   *
   * Returns: the address found, or 0 if no LCD answered.
   * Side effects: I2C traffic; clears and lights the screen when found.
   */
  byte begin();

  /** Current overlay (for tests and decisions in TaskLot). */
  Overlay overlay() const;

  /**
   * Stores one rendered lot row, so the lot can be redrawn after an overlay without
   * printing it to serial again. Does not draw; call paint().
   */
  void setLotRow(byte row, const char* text);

  /** Draws the current overlay, or the lot. Only changed rows go over I2C. */
  void paint();

  /** Switches to ORDER IN PROGRESS, flash phase "on". Does not draw. */
  void showOrdering(uint32_t now);

  /**
   * Switches to YOUR ORDER without touching the page or timeout (the PLAY command).
   * Does not draw.
   */
  void resumeReadback();

  /**
   * Switches to YOUR ORDER at page 1 with a PLAY_MS timeout (a labelled car at the
   * speaker). Does not draw.
   */
  void startReadback(uint32_t now);

  /** As startReadback(), and restarts the page timer (FULLSHOW). Does not draw. */
  void startFullTextReadback(uint32_t now);

  /** Drops YOUR ORDER if it is showing (the LOT command). Does not draw. */
  void closeReadback();

  /**
   * Drops ORDER IN PROGRESS or YOUR ORDER if either is showing, but lets an
   * announcement run out (the DONE command). Does not draw.
   */
  void closeOrderScreens();

  /** Drops any overlay, back to the lot. Does not draw. */
  void closeOverlay();

  /**
   * Flashes `message` over the lot for ANNOUNCE_MS. The lot is already rendered and
   * printed by the time this runs; it appears when the announcement expires.
   *
   * Params: message - a string literal (kept by pointer); now - millis().
   * Side effects: draws.
   */
  void announce(const char* message, uint32_t now);

  /**
   * Advances flashing, paging and timeouts. Costs nothing when no overlay is up.
   *
   * Params: now - millis().
   * Returns: true if a timed read-back just ended (the caller clears OrderState.playing).
   * Side effects: may draw.
   */
  bool tick(uint32_t now);

 private:
  void writeRow(byte row, const char* text);
  void centreRow(byte row, const char* text);
  void paintOrdering();
  void paintAnnouncement();
  void paintReadback();

  const CarRegistry& cars_;
  const ReadbackText& text_;
  const OrderState& order_;

  LiquidCrystal_I2C lcd_;
  byte address_;  // 0 = no screen

  Overlay overlay_;
  const char* announceMessage_;
  uint32_t announceUntil_;
  uint32_t flashAt_;  // last time the flash phase flipped
  bool flashOn_;

  byte page_;
  uint32_t pageAt_;
  uint32_t playUntil_;  // 0 = no timeout

  char lotRows_[LCD_ROWS][LCD_COLS + 1];
  char shown_[LCD_ROWS][LCD_COLS + 1];  // what is physically on the glass
};

#endif  // TASKLOT_LCD_VIEW_H
