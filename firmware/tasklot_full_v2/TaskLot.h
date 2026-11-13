// TaskLot.h - the drive-through: turns reads and commands into lot changes, serial
// events and screens.
//
// Role: the coordinator. It owns the interaction state (who is ordering, what is being
// read back) and the lane debouncers, and wires the other objects together:
//
//   RfidSlot x6 --reads--> TaskLot --labels--> CarRegistry
//                             |  \--occupancy--> ParkingLot
//                             |  \--events-----> SerialProtocol --> laptop
//                             \----screens-----> LcdView --> LCD
//
// The interaction, in one paragraph: each car is one task, and its sticker is a key,
// not a container. Drive a blank car past the SPEAKER and you are placing an order:
// the laptop starts recording and the screen belongs to that order. Park it in a SPACE
// and the order ends; coming to rest is the stop gesture, which is why there is no stop
// button or stop command. The space is the priority: space 1 is line 1. Drive a car
// that already has a task past the speaker and its task is read back on the screen.
// Drive it through the PICKUP lane and the task is done: the label is blanked and the
// car is a clean key again. The board never decides a task is done on its own; a quiet
// space is just a quiet space, and only a hand carrying the car through pickup ends it.

#ifndef TASKLOT_TASKLOT_H
#define TASKLOT_TASKLOT_H

#include "CarRegistry.h"
#include "LaneDebouncer.h"
#include "LcdView.h"
#include "OrderState.h"
#include "ParkingLot.h"
#include "ReadbackText.h"
#include "RfidSlot.h"
#include "SerialProtocol.h"
#include "config.h"

class TaskLot {
 public:
  /**
   * Params: spaces - the four space readers, space 1 first; lanes - the speaker and
   *   pickup readers, indexed by LANE_SPEAKER / LANE_PICKUP; protocol - the serial
   *   link. The arrays must outlive this object (they are globals in the sketch).
   */
  TaskLot(RfidSlot* const* spaces, RfidSlot* const* lanes, SerialProtocol& protocol);

  /**
   * Boot: deselects every reader, starts SPI and I2C, initialises the readers, prints
   * the banner with a health line per reader, finds the LCD, restores EEPROM (if
   * REMEMBER), prints help and the lot. Call once from setup() after Serial.begin().
   */
  void begin();

  /** Runs every complete command waiting on the serial port. */
  void readCommands();

  /**
   * Polls the four spaces in order: an empty space for an arrival, an occupied one
   * with a presence ping (USE_PRESENCE 1), or every space for arrivals only
   * (USE_PRESENCE 0).
   */
  void pollSpaces();

  /**
   * Polls the speaker lane, then the pickup lane. Call after pollSpaces(), so a car
   * carried out of a space is marked gone before a lane sees it.
   */
  void pollLanes();

  /** Advances screen timers (flashing, paging, timeouts). Never blocks. */
  void tickScreen();

 private:
  int8_t identify(const Uid& uid);
  void checkArrival(byte space);
  void checkStillThere(byte space);
  void checkLane(byte lane);
  void carArrived(byte space, int8_t car);
  void speakerPass(int8_t car);
  void pickupPass(int8_t car);
  void printVacated(byte releasedMask, int8_t car);
  void blankLabel(int8_t car);
  void printLot();
  void runCommand(const char* line);

  RfidSlot* const* spaces_;
  RfidSlot* const* lanes_;
  SerialProtocol& protocol_;

  CarRegistry cars_;
  ParkingLot lot_;
  ReadbackText readback_;
  OrderState order_;
  LcdView view_;
  LaneDebouncer laneDebounce_[NUM_LANES];
};

#endif  // TASKLOT_TASKLOT_H
