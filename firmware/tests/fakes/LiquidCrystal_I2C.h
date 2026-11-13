// LiquidCrystal_I2C.h (host fake) - a 20 x 4 character LCD as a grid of chars.
//
// Role: replaces Frank de Brabander's library on the host. Every write lands in one
// shared "glass" grid that tests read with fake::glassRow(), so a test sees exactly
// what a person standing at the lot would see. Copies of the object share the glass,
// which matches the sketch's habit of re-assigning the global once the I2C address is
// known. Used by firmware/tests only.

#ifndef TASKLOT_FAKE_LIQUIDCRYSTAL_I2C_H
#define TASKLOT_FAKE_LIQUIDCRYSTAL_I2C_H

#include <Arduino.h>

#include <string>

class LiquidCrystal_I2C : public Print {
 public:
  /** The address and geometry are ignored: there is one 20 x 4 glass. */
  LiquidCrystal_I2C(uint8_t /*address*/, uint8_t /*cols*/, uint8_t /*rows*/) {}

  /** Clears the glass and marks the screen as initialised. */
  void init();
  void backlight() {}

  /** Fills the glass with spaces and homes the cursor. */
  void clear();

  void setCursor(uint8_t col, uint8_t row);

  /** Puts `c` at the cursor and advances it. Writes past the row end are dropped. */
  size_t write(uint8_t c) override;
  using Print::write;
};

namespace fake {

/** Returns row `row` of the glass (20 characters), or "" before init(). */
std::string glassRow(int row);

}  // namespace fake

#endif  // TASKLOT_FAKE_LIQUIDCRYSTAL_I2C_H
