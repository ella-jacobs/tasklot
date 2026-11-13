// OrderState.h - the drive-through interaction in progress: who is ordering, and whose
// task is being read back.
//
// Role: owned and changed only by TaskLot; LcdView holds a const reference so the
// ORDER IN PROGRESS and YOUR ORDER screens always show the car TaskLot is acting on.

#ifndef TASKLOT_ORDER_STATE_H
#define TASKLOT_ORDER_STATE_H

#include "config.h"

/** At most one order and one read-back at a time. NO_CAR means none. */
struct OrderState {
  // The car whose order is open: a blank car passed the speaker and has not parked or
  // been collected yet. The laptop is recording for this car.
  int8_t ordering;
  // The car whose task is on the YOUR ORDER screen.
  int8_t playing;
};

#endif  // TASKLOT_ORDER_STATE_H
