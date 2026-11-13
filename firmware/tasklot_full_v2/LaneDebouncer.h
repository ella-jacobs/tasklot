// LaneDebouncer.h - turns repeated reads of a car on a lane into one pass.
//
// Role: the speaker and pickup lanes are places a car drives PAST, so one sweep of a
// hand must be one event. A tag lingering in a lane reader's field is read again and
// again; without this, one pass would fire many times and restart the laptop's
// recording mid-sentence. Pure logic (no hardware), tested on the host.

#ifndef TASKLOT_LANE_DEBOUNCER_H
#define TASKLOT_LANE_DEBOUNCER_H

#include "config.h"

/** Debounce state for one lane: the last car it saw and when. */
class LaneDebouncer {
 public:
  LaneDebouncer();

  /**
   * Decides whether a read of `car` at `now` is a new pass.
   *
   * The same car re-read inside LANE_COOLDOWN_MS of its previous read is the same
   * pass. The window slides while the car lingers, so it is lifting the car off and
   * leaving it off for the cooldown that re-arms the lane. A different car is always a
   * new pass, immediately.
   *
   * Params: car - car index read on this lane; now - millis().
   * Returns: true if this read is a new pass and should be acted on.
   * Side effects: remembers `car` and `now` for the next call.
   */
  bool accept(int8_t car, uint32_t now);

 private:
  int8_t lastCar_;
  uint32_t lastAt_;
};

#endif  // TASKLOT_LANE_DEBOUNCER_H
