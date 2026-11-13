// Uid.cpp - UID comparison and the partial-read filter. See Uid.h.

#include "Uid.h"

namespace {
// The shortest UID ISO 14443A defines (single size) is 4 bytes.
const byte MIN_UID_LEN = 4;
// NTAG213 UIDs are not mostly zero; this many zero bytes means a truncated read.
const byte MAX_ZERO_BYTES = 2;
}  // namespace

bool Uid::equals(const Uid& other) const {
  if (size != other.size) return false;
  for (byte b = 0; b < size; b++) {
    if (bytes[b] != other.bytes[b]) return false;
  }
  return true;
}

bool Uid::isPlausible() const {
  if (size < MIN_UID_LEN) return false;

  byte zeros = 0;
  for (byte b = 0; b < size; b++) {
    if (bytes[b] == 0) zeros++;
  }
  if (zeros > MAX_ZERO_BYTES) return false;

  // A trailing run of zeros is where a read that died halfway stops.
  if (bytes[size - 1] == 0 && bytes[size - 2] == 0) return false;
  return true;
}
