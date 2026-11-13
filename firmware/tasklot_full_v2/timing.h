// timing.h - millis() arithmetic that survives the 32-bit wrap.
//
// Role: every timer in the sketch (presence timeout, lane cooldown, flashing, paging,
// read-back timeout) compares timestamps through these two helpers. millis() wraps
// after about 49.7 days; unsigned subtraction and a signed difference both stay
// correct across the wrap, where a plain `now >= deadline` would not.

#ifndef TASKLOT_TIMING_H
#define TASKLOT_TIMING_H

#include <stdint.h>

/**
 * Milliseconds from `since` to `now`, correct across a millis() wrap.
 *
 * Params: now - the current millis(); since - an earlier millis().
 * Returns: now - since, modulo 2^32.
 */
inline uint32_t elapsedMs(uint32_t now, uint32_t since) { return now - since; }

/**
 * Whether `deadline` has been reached, correct across a millis() wrap.
 *
 * Params: now - the current millis(); deadline - a millis() value set in the future.
 * Returns: true once now is at or past deadline. Valid while the two are within
 *   about 24.8 days of each other, which every timer here is by a wide margin.
 */
inline bool deadlineReached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

#endif  // TASKLOT_TIMING_H
