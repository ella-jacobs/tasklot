// CarRegistry.cpp - UID -> car -> label, with optional EEPROM mirroring.
// See CarRegistry.h for the EEPROM layout.

#include "CarRegistry.h"

#if REMEMBER
#include <EEPROM.h>
#endif

#if REMEMBER
namespace {
const byte EE_MAGIC = 0x7A;
const byte EE_VERSION = 1;  // bump if the layout below changes
const int EE_ADDR_MAGIC = 0;
const int EE_ADDR_VERSION = 1;
const int EE_ADDR_COUNT = 2;
const int EE_HEADER_LEN = 3;
// Per car: the UID length byte, the full UID buffer, the label with its NUL.
const int EE_PER_CAR = 1 + UID_MAX_LEN + (TASK_LEN + 1);
const int EE_OFFSET_UID = 1;
const int EE_OFFSET_LABEL = 1 + UID_MAX_LEN;
// Written over the magic byte by forget(): one byte is enough to invalidate the copy.
const byte EE_INVALID = 0xFF;

int carBase(byte car) { return EE_HEADER_LEN + car * EE_PER_CAR; }
}  // namespace
#endif

CarRegistry::CarRegistry() : count_(0) {
  for (byte c = 0; c < MAX_CARS; c++) {
    known_[c].size = 0;
    for (byte b = 0; b < UID_MAX_LEN; b++) known_[c].bytes[b] = 0;
    labels_[c][0] = '\0';
  }
}

int8_t CarRegistry::find(const Uid& uid) const {
  for (byte c = 0; c < count_; c++) {
    if (known_[c].equals(uid)) return c;
  }
  return NO_CAR;
}

CarRegistry::AddResult CarRegistry::add(const Uid& uid) {
  if (count_ >= MAX_CARS) return {FULL, NO_CAR};
  if (!uid.isPlausible()) return {IMPLAUSIBLE, NO_CAR};

  // Copy only the valid bytes; the rest of the slot stays zero, so the EEPROM image
  // does not depend on whatever the reader's buffer held past the UID.
  Uid& slot = known_[count_];
  slot.size = uid.size;
  for (byte b = 0; b < uid.size; b++) slot.bytes[b] = uid.bytes[b];

  int8_t car = count_;
  count_++;
  saveAll();
  return {ADDED, car};
}

byte CarRegistry::count() const { return count_; }

const Uid& CarRegistry::uidOf(int8_t car) const { return known_[car]; }

const char* CarRegistry::label(int8_t car) const { return labels_[car]; }

bool CarRegistry::hasLabel(int8_t car) const { return labels_[car][0] != '\0'; }

void CarRegistry::setLabel(int8_t car, const char* text) {
  byte i = 0;
  for (; i < TASK_LEN && text[i]; i++) labels_[car][i] = text[i];
  labels_[car][i] = '\0';
  saveCar(car);
}

void CarRegistry::clearLabel(int8_t car) {
  labels_[car][0] = '\0';
  saveCar(car);
}

void CarRegistry::clearAllLabels() {
  // Every slot, registered or not, so the EEPROM image matches RAM exactly.
  for (byte c = 0; c < MAX_CARS; c++) clearLabel(c);
}

#if REMEMBER

void CarRegistry::saveHeader() {
  EEPROM.update(EE_ADDR_MAGIC, EE_MAGIC);
  EEPROM.update(EE_ADDR_VERSION, EE_VERSION);
  EEPROM.update(EE_ADDR_COUNT, count_);
}

void CarRegistry::saveCar(byte car) {
  int at = carBase(car);
  EEPROM.update(at, known_[car].size);
  for (byte b = 0; b < UID_MAX_LEN; b++) EEPROM.update(at + EE_OFFSET_UID + b, known_[car].bytes[b]);
  for (byte i = 0; i <= TASK_LEN; i++) EEPROM.update(at + EE_OFFSET_LABEL + i, labels_[car][i]);
}

void CarRegistry::saveAll() {
  saveHeader();
  for (byte c = 0; c < count_; c++) saveCar(c);
}

CarRegistry::LoadStatus CarRegistry::load() {
  if (EEPROM.read(EE_ADDR_MAGIC) != EE_MAGIC || EEPROM.read(EE_ADDR_VERSION) != EE_VERSION) {
    return LOAD_NOTHING_SAVED;
  }
  byte n = EEPROM.read(EE_ADDR_COUNT);
  if (n > MAX_CARS) return LOAD_BAD_COUNT;

  count_ = n;
  for (byte c = 0; c < count_; c++) {
    int at = carBase(c);
    known_[c].size = EEPROM.read(at);
    if (known_[c].size > UID_MAX_LEN) known_[c].size = UID_MAX_LEN;  // never overrun
    for (byte b = 0; b < UID_MAX_LEN; b++) known_[c].bytes[b] = EEPROM.read(at + EE_OFFSET_UID + b);
    for (byte i = 0; i <= TASK_LEN; i++) labels_[c][i] = EEPROM.read(at + EE_OFFSET_LABEL + i);
    labels_[c][TASK_LEN] = '\0';  // whatever was stored, end it
  }
  return LOAD_RESTORED;
}

bool CarRegistry::forget() {
  EEPROM.update(EE_ADDR_MAGIC, EE_INVALID);
  return true;
}

#else  // REMEMBER == 0: persistence compiles away.

void CarRegistry::saveHeader() {}
void CarRegistry::saveCar(byte car) { (void)car; }
void CarRegistry::saveAll() {}
CarRegistry::LoadStatus CarRegistry::load() { return LOAD_DISABLED; }
bool CarRegistry::forget() { return false; }

#endif
