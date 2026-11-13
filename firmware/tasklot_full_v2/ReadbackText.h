// ReadbackText.h - the full task text for a read-back, and its word-wrapped rows.
//
// Role: the board only keeps an 18-character label per car; the sentence that was
// actually said lives on the laptop. For a read-back the laptop sends it in chunks
// (FULLCLR, then FULL <chunk>..., then FULLSHOW <n>) because the AVR's serial receive
// buffer is only 64 bytes. This class collects the chunks and wraps them into LCD rows
// for LcdView to page through. Pure logic, host-tested.

#ifndef TASKLOT_READBACK_TEXT_H
#define TASKLOT_READBACK_TEXT_H

#include "config.h"

class ReadbackText {
 public:
  /** Starts empty: no text, no rows. */
  ReadbackText();

  /**
   * Empties the text buffer but keeps the wrapped rows, so a read-back already on
   * screen keeps showing while the next text arrives (FULLCLR).
   */
  void clearText();

  /** Empties both the text and the wrapped rows (CLEAR, or a new read-back starting). */
  void clearAll();

  /**
   * Appends a chunk, with one space between chunks, up to FULL_LEN characters. Anything
   * past FULL_LEN is dropped.
   *
   * Params: chunk - NUL-terminated.
   */
  void append(const char* chunk);

  /**
   * Re-wraps the text into rows of at most LCD_COLS characters, breaking at the last
   * space that fits when there is one (a word longer than a row is split), and
   * dropping the spaces at each break. At most WRAP_LINES rows; the rest is dropped.
   */
  void wrap();

  /** Number of wrapped rows (0..WRAP_LINES). */
  byte rowCount() const;

  /** Wrapped row `index` (0 <= index < rowCount()). */
  const char* row(byte index) const;

 private:
  char text_[FULL_LEN + 1];
  byte length_;
  char rows_[WRAP_LINES][LCD_COLS + 1];
  byte rowCount_;
};

#endif  // TASKLOT_READBACK_TEXT_H
