// RfidSlot.cpp - the bench-verified MFRC522 call sequences. See RfidSlot.h.

#include "RfidSlot.h"

namespace {
// VersionReg values seen on real boards.
const byte VERSION_NXP_V1 = 0x91;
const byte VERSION_NXP_V2 = 0x92;
const byte VERSION_CLONE_A = 0x88;
const byte VERSION_CLONE_B = 0x12;
// What the bus reads when nothing drives MISO (0x00) or it floats high (0xFF).
const byte VERSION_NONE_LOW = 0x00;
const byte VERSION_NONE_HIGH = 0xFF;
}  // namespace

ReaderHealth classifyReaderVersion(byte version) {
  if (version == VERSION_NONE_LOW || version == VERSION_NONE_HIGH) return READER_SILENT;
  if (version == VERSION_NXP_V1 || version == VERSION_NXP_V2) return READER_GENUINE;
  if (version == VERSION_CLONE_A || version == VERSION_CLONE_B) return READER_CLONE;
  return READER_UNEXPECTED;
}

RfidSlot::RfidSlot(byte ssPin, byte rstPin) : reader_(ssPin, rstPin), ssPin_(ssPin) {}

void RfidSlot::deselect() {
  pinMode(ssPin_, OUTPUT);
  digitalWrite(ssPin_, HIGH);
}

void RfidSlot::begin() { reader_.PCD_Init(); }

byte RfidSlot::ssPin() const { return ssPin_; }

byte RfidSlot::versionByte() { return reader_.PCD_ReadRegister(MFRC522::VersionReg); }

bool RfidSlot::readArrival(Uid& out) {
  if (!(reader_.PICC_IsNewCardPresent() && reader_.PICC_ReadCardSerial())) return false;

  out.size = reader_.uid.size;
  for (byte b = 0; b < UID_MAX_LEN; b++) out.bytes[b] = reader_.uid.uidByte[b];

  reader_.PICC_HaltA();
  reader_.PCD_StopCrypto1();
  return true;
}

bool RfidSlot::isStillPresent() {
  byte atqa[2];
  byte size = sizeof(atqa);
  MFRC522::StatusCode status = reader_.PICC_WakeupA(atqa, &size);
  reader_.PICC_HaltA();
  return status == MFRC522::STATUS_OK || status == MFRC522::STATUS_COLLISION;
}
