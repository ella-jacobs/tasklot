// TaskLot.cpp - what each read and each command does. See TaskLot.h for the overview
// and firmware/README.md for the state machine as a table.

#include "TaskLot.h"

#include <SPI.h>
#include <Wire.h>

namespace {
// Announcements. ORDER IS IN only fires when a task was actually just recorded (an
// order was open when the car parked); ALL DONE!! only when a car that had a label is
// collected or DONE'd. Moving a loaded car between spaces reorders silently.
const char* const ANNOUNCE_ORDER_IN = "ORDER IS IN";
const char* const ANNOUNCE_ALL_DONE = "ALL DONE!!";
}  // namespace

TaskLot::TaskLot(RfidSlot* const* spaces, RfidSlot* const* lanes, SerialProtocol& protocol)
    : spaces_(spaces),
      lanes_(lanes),
      protocol_(protocol),
      order_{NO_CAR, NO_CAR},
      view_(cars_, readback_, order_) {}

// ===========================================================================
// Boot
// ===========================================================================

void TaskLot::begin() {
  // Park every SS pin HIGH before the bus starts; see RfidSlot::deselect().
  for (byte s = 0; s < NUM_SPACES; s++) spaces_[s]->deselect();
  for (byte l = 0; l < NUM_LANES; l++) lanes_[l]->deselect();

  SPI.begin();
  Wire.begin();

  for (byte s = 0; s < NUM_SPACES; s++) spaces_[s]->begin();
  for (byte l = 0; l < NUM_LANES; l++) lanes_[l]->begin();

  protocol_.printBanner();

  // Reader health first: find a dead reader here, not mid-demo.
  for (byte s = 0; s < NUM_SPACES; s++) {
    protocol_.printSpaceReader(s, spaces_[s]->ssPin(), spaces_[s]->versionByte());
  }
  for (byte l = 0; l < NUM_LANES; l++) {
    protocol_.printLaneReader(l, lanes_[l]->ssPin(), lanes_[l]->versionByte());
  }
  protocol_.printRailHint();

  protocol_.printLcdResult(view_.begin());
  CarRegistry::LoadStatus loaded = cars_.load();
  protocol_.printLoadResult(loaded, cars_.count());

  protocol_.printHelp();
  printLot();
}

// ===========================================================================
// Polling
// ===========================================================================

void TaskLot::readCommands() {
  char* line;
  while ((line = protocol_.readLine()) != nullptr) runCommand(line);
}

void TaskLot::pollSpaces() {
  for (byte s = 0; s < NUM_SPACES; s++) {
#if USE_PRESENCE
    if (lot_.occupant(s) == NO_CAR) {
      checkArrival(s);
    } else {
      checkStillThere(s);
    }
#else
    checkArrival(s);
#endif
  }
}

void TaskLot::pollLanes() {
  checkLane(LANE_SPEAKER);
  checkLane(LANE_PICKUP);
}

void TaskLot::tickScreen() {
  if (view_.tick(millis())) order_.playing = NO_CAR;  // the read-back timed out
}

// ===========================================================================
// Reads
// ===========================================================================

// Maps a UID to a car, registering it on first sight. Every failure is reported as
// "no car slots left" as well, as the original sketch did (see README, known quirks).
int8_t TaskLot::identify(const Uid& uid) {
  int8_t car = cars_.find(uid);
  if (car != NO_CAR) return car;

  CarRegistry::AddResult added = cars_.add(uid);
  switch (added.status) {
    case CarRegistry::ADDED:
      protocol_.printNewCar(added.car, uid);
      return added.car;
    case CarRegistry::IMPLAUSIBLE:
      protocol_.printBadRead(uid);
      protocol_.printNoSlotsLeft();
      return NO_CAR;
    case CarRegistry::FULL:
    default:
      protocol_.printNoSlotsLeft();
      return NO_CAR;
  }
}

void TaskLot::checkArrival(byte space) {
  Uid uid;
  if (!spaces_[space]->readArrival(uid)) return;
  int8_t car = identify(uid);
  if (car != NO_CAR) carArrived(space, car);
}

void TaskLot::checkStillThere(byte space) {
  bool present = spaces_[space]->isStillPresent();
  int8_t left = lot_.updatePresence(space, present, millis());
  if (left == NO_CAR) return;
  protocol_.printLeft(space, left);
  printLot();
}

// A lane is somewhere a car drives PAST: arrival reads only, never presence, never an
// occupant, never on the lot.
void TaskLot::checkLane(byte lane) {
  Uid uid;
  if (!lanes_[lane]->readArrival(uid)) return;
  int8_t car = identify(uid);
  if (car == NO_CAR) return;
  if (!laneDebounce_[lane].accept(car, millis())) return;  // same pass, already handled

  if (lane == LANE_SPEAKER) {
    speakerPass(car);
  } else {
    pickupPass(car);
  }
}

// ===========================================================================
// The three gestures
// ===========================================================================

// PARKING IS THE STOP GESTURE. Whatever was ordering, the order is over the moment a
// car comes to rest. Parking also cuts a read-back short.
void TaskLot::carArrived(byte space, int8_t car) {
  uint32_t now = millis();
  bool changed = lot_.park(space, car, now);

  // speakerPass() only opens an order for a BLANK car, so "an order was open" is
  // exactly "a task was just recorded".
  bool orderJustClosed = order_.ordering != NO_CAR;
  bool interactionOpen = orderJustClosed || order_.playing != NO_CAR;
  order_.playing = NO_CAR;
  if (!orderJustClosed) view_.closeOverlay();
  order_.ordering = NO_CAR;

  if (changed) {
    // A car holds one space: arriving here releases wherever it was.
    printVacated(lot_.vacateElsewhere(car, space), car);
    protocol_.printParked(space, car);
    printLot();
  } else if (interactionOpen) {
    printLot();  // nothing moved, but the order or read-back closed: show the lot
  }

  // The lot is already rendered underneath; it appears when the announcement ends.
  if (orderJustClosed) view_.announce(ANNOUNCE_ORDER_IN, now);
}

// THE SPEAKER: one reader, two jobs, and the car decides which. A blank car is placing
// an order. A car that already carries a task has it read back, like a real
// drive-through speaker repeating your order. The board owns the screen; the laptop
// holds the full sentence and sends it with FULL / FULLSHOW.
// One speaker, one car at a time: a second car simply replaces the first.
void TaskLot::speakerPass(int8_t car) {
  uint32_t now = millis();
  if (cars_.hasLabel(car)) {
    protocol_.printPlayback(car);
    order_.ordering = NO_CAR;
    order_.playing = car;
    // The full text takes the laptop about a second to send. Drop the previous car's
    // text now, so the screen shows THIS car's label first instead of somebody else's
    // task.
    readback_.clearAll();
    view_.startReadback(now);
    printLot();
    return;
  }

  protocol_.printOrdering(car);
  order_.ordering = car;
  order_.playing = NO_CAR;
  view_.showOrdering(now);
  printLot();
}

// THE PICKUP LANE: the task is done. Blank the label (the car is a key, and an empty
// key is ready to order again) and release its space. Collecting a car that never had
// a task is not an error, just a car being carried around: report it, but no receipt.
void TaskLot::pickupPass(int8_t car) {
  protocol_.printCollected(car);
  bool hadLabel = cars_.hasLabel(car);
  blankLabel(car);

  // Release the space now instead of waiting GONE_MS for presence to notice, so the
  // screen updates on the gesture, and so pickup works with USE_PRESENCE 0 too.
  printVacated(lot_.vacateElsewhere(car, NO_CAR), car);

  // An order for this car can never be parked closed now, so pickup closes it. This
  // is the only other way an order ends.
  if (order_.ordering == car) order_.ordering = NO_CAR;
  if (order_.playing == car) order_.playing = NO_CAR;
  view_.closeOverlay();

  printLot();
  if (hadLabel) view_.announce(ANNOUNCE_ALL_DONE, millis());
}

// ===========================================================================
// Output helpers
// ===========================================================================

void TaskLot::printVacated(byte releasedMask, int8_t car) {
  for (byte s = 0; s < NUM_SPACES; s++) {
    if (releasedMask & (1 << s)) protocol_.printLeft(s, car);
  }
}

// Blanks a label and echoes it in the same shape as any other label change, so the
// laptop updates the same way whether it or the pickup lane did it.
void TaskLot::blankLabel(int8_t car) {
  cars_.clearLabel(car);
  protocol_.printTaskEcho(car, cars_.label(car));
}

// Always prints to serial: the laptop parses it, and the two rule lines are what paces
// its sender. The glass is left to LcdView, which may be showing an overlay instead.
void TaskLot::printLot() {
  protocol_.printLotRule();
  for (byte s = 0; s < NUM_SPACES; s++) {
    char line[LCD_COLS + 1];
    lot_.renderLine(s, cars_, line);
    protocol_.printLotLine(line);
    view_.setLotRow(s, line);
  }
  protocol_.printLotRule();
  view_.paint();
}

// ===========================================================================
// Commands from the laptop (DESIGN.md section 3.2)
// ===========================================================================

void TaskLot::runCommand(const char* line) {
  Command cmd = SerialProtocol::parse(line);
  switch (cmd.kind) {
    case Command::CMD_PING:
      protocol_.printPong();
      return;

    // "Show me the lot", so it also ends a read-back.
    case Command::CMD_LOT:
      order_.playing = NO_CAR;
      view_.closeReadback();
      printLot();
      return;

    case Command::CMD_FORGET:
      protocol_.printForgetResult(cars_.forget());
      return;

    // The speaker reader is the real source of this; the command lets the browser
    // simulator drive a board, which is the fallback when a reader goes quiet. It goes
    // through the same speakerPass() so the two cannot drift.
    case Command::CMD_ORDER:
      speakerPass(cmd.car());
      return;

    // A read-back for the simulator. No timeout (DESIGN.md open question 9.2).
    case Command::CMD_PLAY:
      order_.ordering = NO_CAR;
      order_.playing = cmd.car();
      view_.resumeReadback();
      printLot();
      return;

    case Command::CMD_FULL_CLEAR:
      readback_.clearText();
      return;

    case Command::CMD_FULL_SHOW:
      readback_.wrap();
      order_.ordering = NO_CAR;
      order_.playing = cmd.car();
      view_.startFullTextReadback(millis());
      printLot();
      return;

    case Command::CMD_FULL_APPEND:
      readback_.append(cmd.text);
      return;

    case Command::CMD_CLEAR:
      cars_.clearAllLabels();
      readback_.clearAll();
      protocol_.printTasksCleared();
      printLot();
      return;

    // The task is finished, so the car goes back to being a blank key. The pickup lane
    // does this from the hardware side; DONE is the laptop's override.
    case Command::CMD_DONE: {
      int8_t car = cmd.car();
      bool hadLabel = cars_.hasLabel(car);
      blankLabel(car);
      order_.playing = NO_CAR;
      order_.ordering = NO_CAR;
      printLot();
      if (hadLabel) view_.announce(ANNOUNCE_ALL_DONE, millis());
      return;
    }

    case Command::CMD_SET_LABEL: {
      int8_t car = cmd.car();
      cars_.setLabel(car, cmd.text);
      protocol_.printTaskEcho(car, cars_.label(car));  // so the laptop can confirm it landed
      printLot();
      return;
    }

    case Command::CMD_BAD_CAR:
      protocol_.printBadCarNumber(cmd.number);
      return;

    case Command::CMD_UNKNOWN:
    default:
      protocol_.printUnknownCommand(cmd.text);
      return;
  }
}
