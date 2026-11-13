// RfidSlot.h - one RC522 reader on the shared SPI bus: arrivals, presence, health.
//
// Role: the only code that talks to the MFRC522 library. The four spaces and the two
// lanes are each one RfidSlot; what a read MEANS (parked, ordering, collected) is
// decided by TaskLot, not here.
//
// The call sequences in this class are the part of the firmware that was proven on the
// bench, and are kept exactly:
//   arrival:  PICC_IsNewCardPresent -> PICC_ReadCardSerial -> PICC_HaltA -> PCD_StopCrypto1
//   presence: PICC_WakeupA -> PICC_HaltA

#ifndef TASKLOT_RFID_SLOT_H
#define TASKLOT_RFID_SLOT_H

#include <MFRC522.h>

#include "Uid.h"
#include "config.h"

/** What a reader's VersionReg says about it at boot. */
enum ReaderHealth : byte {
  READER_GENUINE,     // 0x91 / 0x92: an NXP MFRC522
  READER_CLONE,       // 0x88 / 0x12: a common clone; works fine
  READER_SILENT,      // 0x00 / 0xFF: not answering on SPI (wiring, SS, or power)
  READER_UNEXPECTED,  // anything else: answering, but not a known chip
};

/**
 * Classifies a VersionReg value.
 *
 * Params: version - the byte read from VersionReg.
 * Returns: the matching ReaderHealth.
 */
ReaderHealth classifyReaderVersion(byte version);

/** One RC522 reader, identified by its chip-select pin. */
class RfidSlot {
 public:
  /**
   * Params: ssPin - this reader's chip-select pin; rstPin - the shared reset pin.
   * Does not touch the hardware; call deselect() and begin() from setup().
   */
  RfidSlot(byte ssPin, byte rstPin);

  /**
   * Drives this reader's SS pin HIGH (not selected).
   *
   * Every reader must be deselected before SPI.begin() and before the first
   * PCD_Init(): PCD_Init() parks only its own SS pin, so while one reader initialises
   * the others' SS pins are still floating inputs, and any of them can read as
   * selected. With six readers that is the classic way the bus goes quiet.
   *
   * Side effects: configures the pin as an OUTPUT.
   */
  void deselect();

  /** Initialises the reader (PCD_Init). Side effects: SPI traffic, resets the chip. */
  void begin();

  /** The chip-select pin, for boot messages. */
  byte ssPin() const;

  /**
   * Reads VersionReg. SPI needs almost no current, so a good version with no tag
   * reads points at a starved 3.3 V rail rather than wiring.
   *
   * Returns: the raw version byte.
   */
  byte versionByte();

  /**
   * Polls for a tag entering the field, and if one is read, puts it to sleep.
   *
   * A halted tag ignores this poll until it leaves the field and comes back, which is
   * why a car resting on a space is tracked with isStillPresent() instead.
   *
   * Params: out - receives the UID when a tag is read.
   * Returns: true if a tag was read (out is filled), false otherwise (out untouched).
   * Side effects: on a read, halts the tag and stops any crypto session.
   */
  bool readArrival(Uid& out);

  /**
   * Pings the tag resting in the field, then puts it back to sleep.
   *
   * WakeupA (WUPA) is answered by a halted tag, where the normal "any new card?"
   * request is not. A collision means two tags answered, which still means one is here.
   *
   * Returns: true if a tag answered.
   * Side effects: halts the tag again.
   */
  bool isStillPresent();

 private:
  MFRC522 reader_;
  byte ssPin_;
};

#endif  // TASKLOT_RFID_SLOT_H
