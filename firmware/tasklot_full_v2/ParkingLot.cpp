// ParkingLot.cpp - occupancy of the four spaces. See ParkingLot.h.

#include "ParkingLot.h"

#include "timing.h"

namespace {
// "1>" - the space number and the marker before the label.
const byte LOT_PREFIX_LEN = 2;
}  // namespace

ParkingLot::ParkingLot() {
  for (byte s = 0; s < NUM_SPACES; s++) {
    occupant_[s] = NO_CAR;
    lastSeen_[s] = 0;
  }
}

int8_t ParkingLot::occupant(byte space) const { return occupant_[space]; }

bool ParkingLot::park(byte space, int8_t car, uint32_t now) {
  bool changed = occupant_[space] != car;
  occupant_[space] = car;
  lastSeen_[space] = now;
  return changed;
}

byte ParkingLot::vacateElsewhere(int8_t car, int8_t keep) {
  byte released = 0;
  for (byte s = 0; s < NUM_SPACES; s++) {
    if (static_cast<int8_t>(s) != keep && occupant_[s] == car) {
      occupant_[s] = NO_CAR;
      released |= static_cast<byte>(1 << s);
    }
  }
  return released;
}

int8_t ParkingLot::updatePresence(byte space, bool present, uint32_t now) {
  if (present) {
    lastSeen_[space] = now;
    return NO_CAR;
  }
  if (elapsedMs(now, lastSeen_[space]) < GONE_MS) return NO_CAR;

  int8_t left = occupant_[space];
  occupant_[space] = NO_CAR;
  return left;
}

void ParkingLot::renderLine(byte space, const CarRegistry& cars, char* out) const {
  out[0] = static_cast<char>('1' + space);
  out[1] = '>';
  char* text = out + LOT_PREFIX_LEN;

  int8_t car = occupant_[space];
  if (car == NO_CAR) {
    text[0] = '-';
    text[1] = '\0';
    return;
  }

  const char* label = cars.label(car);
  if (!label[0]) {
    // Parked, but no label yet: show the car number. MAX_CARS is 8, so one digit.
    text[0] = 'C';
    text[1] = 'A';
    text[2] = 'R';
    text[3] = ' ';
    text[4] = static_cast<char>('1' + car);
    text[5] = '\0';
    return;
  }

  byte i = 0;
  for (; i < LCD_COLS - LOT_PREFIX_LEN && label[i]; i++) text[i] = label[i];
  text[i] = '\0';
}
