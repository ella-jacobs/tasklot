// EEPROM.h (host fake) - the ATmega2560's 4 KB EEPROM as a byte array.
//
// Role: lets the REMEMBER build of the sketch run on the host. Starts erased (0xFF,
// like a new chip). fake::eepromLoad()/eepromSave() copy it to and from a file so a
// test can "power-cycle" the board across two processes. Used by firmware/tests only.

#ifndef TASKLOT_FAKE_EEPROM_H
#define TASKLOT_FAKE_EEPROM_H

#include <stdint.h>

/** EEPROM access. Addresses outside 0..4095 read 0xFF and ignore writes. */
class EEPROMClass {
 public:
  uint8_t read(int address);
  void write(int address, uint8_t value);

  /** Writes only if the stored byte differs (the real call saves wear the same way). */
  void update(int address, uint8_t value);
};

extern EEPROMClass EEPROM;

namespace fake {

/** Replaces the EEPROM contents with the file at `path`, if it exists. */
void eepromLoad(const char* path);

/** Writes the EEPROM contents to `path`. */
void eepromSave(const char* path);

}  // namespace fake

#endif  // TASKLOT_FAKE_EEPROM_H
