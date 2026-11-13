// MFRC522.h (host fake) - an RC522 reader plus a scriptable tag in its field.
//
// Role: replaces miguelbalboa/rfid on the host. Each reader is identified by its SS
// pin, and a test places or removes a tag on that pin with fake::placeTag() and
// fake::removeTag(). The tag follows the ISO 14443A states the sketch depends on:
//
//   - A tag that arrives is IDLE and answers REQA, so PICC_IsNewCardPresent() is true.
//   - PICC_HaltA() puts it in HALT. A halted tag ignores REQA (IsNewCardPresent() is
//     false) but answers WUPA, so PICC_WakeupA() returns STATUS_OK. This is why the
//     sketch uses WakeupA for presence pings.
//   - Taking the tag out of the field resets it; put back, it is IDLE again.
//
// Only the members the sketch calls exist. Used by firmware/tests only.

#ifndef TASKLOT_FAKE_MFRC522_H
#define TASKLOT_FAKE_MFRC522_H

#include <Arduino.h>

class MFRC522 {
 public:
  enum PCD_Register : byte {
    VersionReg = 0x37 << 1,  // same encoding as the real library
  };

  enum StatusCode : byte {
    STATUS_OK,
    STATUS_ERROR,
    STATUS_COLLISION,
    STATUS_TIMEOUT,
  };

  /** A tag UID as the library stores it: up to 10 bytes. */
  struct Uid {
    byte size;
    byte uidByte[10];
    byte sak;
  };

  /** The UID of the last tag read by PICC_ReadCardSerial(). */
  Uid uid;

  /**
   * Registers a reader on `chipSelectPin` so tests can address it by pin.
   *
   * Params: chipSelectPin - the SS pin; resetPowerDownPin - ignored.
   */
  MFRC522(byte chipSelectPin, byte resetPowerDownPin);

  void PCD_Init() {}

  /** Returns the version byte configured with fake::setReaderVersion() (default 0x92). */
  byte PCD_ReadRegister(PCD_Register reg);

  /** True if an IDLE (not halted) tag is in the field. */
  bool PICC_IsNewCardPresent();

  /** Copies the tag's UID into `uid`. Returns false if no tag is in the field. */
  bool PICC_ReadCardSerial();

  /** Halts the tag in the field, if any. Always returns STATUS_OK. */
  StatusCode PICC_HaltA();

  /** No crypto session is modelled; accepted and ignored. */
  void PCD_StopCrypto1() {}

  /** Wakes a tag (halted or idle). STATUS_OK if one is in the field, else STATUS_TIMEOUT. */
  StatusCode PICC_WakeupA(byte* bufferATQA, byte* bufferSize);

 private:
  byte ss_;
};

namespace fake {

/**
 * Puts a tag with the given UID bytes in the field of the reader on `ssPin`.
 * Replaces any tag already there. The new tag starts IDLE.
 */
void placeTag(byte ssPin, const byte* uid, byte size);

/** Takes the tag out of the field of the reader on `ssPin`. */
void removeTag(byte ssPin);

/** Sets what VersionReg reads on `ssPin` (0x00 or 0xFF = "not talking"). */
void setReaderVersion(byte ssPin, byte version);

}  // namespace fake

#endif  // TASKLOT_FAKE_MFRC522_H
