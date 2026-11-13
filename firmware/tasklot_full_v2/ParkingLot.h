// ParkingLot.h - which car is resting on each of the four spaces.
//
// Role: occupancy only. A space is somewhere a car comes to rest, and the space it is
// on is its priority (space 1 is the top line). The rules that make "pick it up and
// move it" reorder the list live here: a car holds at most one space, and a space is
// empty only after GONE_MS of silence. Lanes never appear here; nothing is ever
// "parked at the speaker".
//
// Methods report what changed and leave printing and drawing to the caller (TaskLot),
// which keeps this class free of hardware and host-testable.

#ifndef TASKLOT_PARKING_LOT_H
#define TASKLOT_PARKING_LOT_H

#include "CarRegistry.h"
#include "config.h"

class ParkingLot {
 public:
  /** Starts with every space empty. */
  ParkingLot();

  /** The car on space `space` (0-based), or NO_CAR. */
  int8_t occupant(byte space) const;

  /**
   * Records that `car` was just read arriving on `space`.
   *
   * Does not release any other space the car held; call vacateElsewhere() for that.
   *
   * Params: space - 0..NUM_SPACES-1; car - car index; now - millis().
   * Returns: true if the space's occupant changed (it was empty or held another car).
   * Side effects: sets the occupant and its last-seen time.
   */
  bool park(byte space, int8_t car, uint32_t now);

  /**
   * Empties every space other than `keep` that holds `car`.
   *
   * This is what makes moving a car reorder the list instead of duplicating its label
   * onto two lines: arriving somewhere new releases the old space at once, without
   * waiting for GONE_MS.
   *
   * Params: car - car index; keep - a space to leave alone, or NO_CAR to release all.
   * Returns: a bit mask of the spaces released (bit s = space s).
   */
  byte vacateElsewhere(int8_t car, int8_t keep);

  /**
   * Feeds one presence ping result for an occupied space.
   *
   * One missed ping is not a departure; the space empties only after GONE_MS with no
   * answer. Presence pings do not check WHICH tag answered, so a different car set
   * down inside GONE_MS is taken for the old one (see firmware/README.md).
   *
   * Params: space - an occupied space; present - the ping was answered; now - millis().
   * Returns: the car that left, or NO_CAR if the space is still considered occupied.
   * Side effects: refreshes the last-seen time on an answer; empties the space when
   *   it times out.
   */
  int8_t updatePresence(byte space, bool present, uint32_t now);

  /**
   * Renders one line of the lot exactly as the serial printout and the LCD show it:
   * "<n>>" then the label, "-" for an empty space, or "CAR <n>" for a parked car with
   * no label yet (so the space still reads as occupied).
   *
   * Params: space - 0..NUM_SPACES-1; cars - for labels; out - LCD_COLS + 1 chars.
   * Side effects: writes a NUL-terminated string into `out`.
   */
  void renderLine(byte space, const CarRegistry& cars, char* out) const;

 private:
  int8_t occupant_[NUM_SPACES];
  uint32_t lastSeen_[NUM_SPACES];
};

#endif  // TASKLOT_PARKING_LOT_H
