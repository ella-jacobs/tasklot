// Uid.h - a tag UID as read from an RC522, and the check that it is a whole read.
//
// Role: the value that flows from RfidSlot (which reads it) to CarRegistry (which maps
// it to a car number) and SerialProtocol (which prints it). Plain data, no hardware,
// so it compiles and is tested on the host too.

#ifndef TASKLOT_UID_H
#define TASKLOT_UID_H

#include "config.h"

/** One tag UID: up to UID_MAX_LEN bytes, of which the first `size` are valid. */
struct Uid {
  byte size;
  byte bytes[UID_MAX_LEN];

  /**
   * Whether this UID and `other` are the same tag.
   *
   * Returns: true if the sizes match and every valid byte matches.
   */
  bool equals(const Uid& other) const;

  /**
   * Whether this looks like a complete read rather than one that died halfway.
   *
   * A read that loses the RF field partway through (a starved 3.3 V rail does this)
   * comes back with a run of zero bytes. Two such reads were seen on the bench,
   * 04 D1 60 00 00 00 00 and 04 E1 63 00 00 00 00, both partial reads of real cars;
   * registering them made a new, blank car, so the speaker started recording instead
   * of reading the real car's task back. A "see it twice" rule was tried and reverted:
   * a halted tag is never re-polled, so nothing registered until each car was tapped
   * twice. This check costs nothing and catches the phantoms.
   *
   * Returns: false if the UID is shorter than 4 bytes, has 3 or more zero bytes, or
   *   ends in two zero bytes; true otherwise.
   */
  bool isPlausible() const;
};

#endif  // TASKLOT_UID_H
