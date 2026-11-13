// Wire.h (host fake) - the I2C bus, reduced to what the LCD address scan needs.
//
// Role: the sketch finds the LCD backpack by probing every I2C address. This fake
// answers (endTransmission() == 0) only at the address a test configures with
// fake::setLcdAddress(), so a test can boot with the screen at 0x27, at 0x3F, or
// missing. Used by firmware/tests only.

#ifndef TASKLOT_FAKE_WIRE_H
#define TASKLOT_FAKE_WIRE_H

#include <stdint.h>

/** The I2C bus. Only the address probe is modelled. */
class TwoWire {
 public:
  void begin() {}

  /** Starts a probe of `address`. */
  void beginTransmission(uint8_t address) { probing_ = address; }

  /**
   * Ends the probe.
   *
   * Returns: 0 (ACK) if a device is configured at the probed address, otherwise 2
   *   (address NACK), matching the Arduino Wire return codes.
   */
  uint8_t endTransmission();

 private:
  uint8_t probing_ = 0;
};

extern TwoWire Wire;

namespace fake {

/** Puts the fake LCD backpack at `address`; 0 means no LCD on the bus. */
void setLcdAddress(uint8_t address);

}  // namespace fake

#endif  // TASKLOT_FAKE_WIRE_H
