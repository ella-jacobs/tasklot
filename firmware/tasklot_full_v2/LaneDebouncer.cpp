// LaneDebouncer.cpp - one pass per sweep on a lane reader. See LaneDebouncer.h.

#include "LaneDebouncer.h"

#include "timing.h"

LaneDebouncer::LaneDebouncer() : lastCar_(NO_CAR), lastAt_(0) {}

bool LaneDebouncer::accept(int8_t car, uint32_t now) {
  if (car == lastCar_ && elapsedMs(now, lastAt_) < LANE_COOLDOWN_MS) {
    lastAt_ = now;  // keep sliding while it lingers
    return false;
  }
  lastCar_ = car;
  lastAt_ = now;
  return true;
}
