// unit_tests.cpp - host-side unit tests for each firmware class.
//
// Role: pins the rules each class owns, including the DESIGN.md section 5 edge cases
// that can be tested without hardware (E-09, E-16, E-25 to E-29, E-34, E-42). The
// whole-sketch behaviour is pinned separately by scenarios.cpp and golden/.
//
// Built and run by run_tests.sh against the sketch sources and the fakes. No test
// framework: CHECK() records a failure with its line and keeps going, and main()
// returns non-zero if anything failed.

#include <Arduino.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>

#include <cstdio>
#include <string>

#include "CarRegistry.h"
#include "LaneDebouncer.h"
#include "LcdView.h"
#include "OrderState.h"
#include "ParkingLot.h"
#include "ReadbackText.h"
#include "RfidSlot.h"
#include "SerialProtocol.h"
#include "Uid.h"
#include "config.h"
#include "timing.h"

namespace {

int gChecks = 0;
int gFailures = 0;

/** Records one check; prints the failing expression and line. */
void check(bool ok, const char* expr, int line) {
  gChecks++;
  if (!ok) {
    gFailures++;
    printf("    FAIL line %d: %s\n", line, expr);
  }
}

#define CHECK(cond) check((cond), #cond, __LINE__)
#define CHECK_STR(actual, expected) \
  check(std::string(actual) == std::string(expected), #actual " == " #expected, __LINE__)

/** Builds a Uid from a byte list. */
Uid makeUid(std::initializer_list<int> bytes) {
  Uid u = {0, {0}};
  for (int b : bytes) u.bytes[u.size++] = static_cast<byte>(b);
  return u;
}

const Uid kCarA = makeUid({0x04, 0xA1, 0x10, 0x2B, 0x7C, 0x51, 0x80});
const Uid kCarB = makeUid({0x04, 0xB2, 0x21, 0x3C, 0x8D, 0x62, 0x80});

// A millis() value 1 s before the 32-bit counter wraps.
const uint32_t kNearWrap = 0xFFFFFFFFu - 999u;

// ---------------------------------------------------------------------------

void testTiming() {
  CHECK(elapsedMs(100, 40) == 60);
  CHECK(elapsedMs(5, kNearWrap) == 1005);  // across the wrap (E-42)
  CHECK(!deadlineReached(kNearWrap, kNearWrap + 10));
  CHECK(deadlineReached(kNearWrap + 10, kNearWrap + 10));
  CHECK(deadlineReached(20, kNearWrap + 10));  // deadline before the wrap, now after
  CHECK(!deadlineReached(kNearWrap, 500));     // deadline after the wrap, now before
}

void testUid() {
  CHECK(kCarA.equals(kCarA));
  CHECK(!kCarA.equals(kCarB));
  CHECK(!makeUid({1, 2, 3, 4}).equals(makeUid({1, 2, 3, 4, 5})));

  CHECK(kCarA.isPlausible());
  CHECK(makeUid({0x3A, 0x5B, 0x7C, 0x9D}).isPlausible());
  CHECK(makeUid({0x04, 0x00, 0x11, 0x00, 0x22, 0x33, 0x44}).isPlausible());  // 2 zeros, not trailing
  // E-29: the two partial reads seen on the bench.
  CHECK(!makeUid({0x04, 0xD1, 0x60, 0x00, 0x00, 0x00, 0x00}).isPlausible());
  CHECK(!makeUid({0x04, 0xE1, 0x63, 0x00, 0x00, 0x00, 0x00}).isPlausible());
  CHECK(!makeUid({0x04, 0x5A, 0x6B, 0x7C, 0x8D, 0x00, 0x00}).isPlausible());  // trailing pair
  CHECK(!makeUid({0x00, 0x5A, 0x00, 0x7C, 0x00, 0x11, 0x22}).isPlausible());  // 3 zeros
  CHECK(!makeUid({0x04, 0x5A, 0x6B}).isPlausible());                          // too short
}

void testReaderVersion() {
  CHECK(classifyReaderVersion(0x91) == READER_GENUINE);
  CHECK(classifyReaderVersion(0x92) == READER_GENUINE);
  CHECK(classifyReaderVersion(0x88) == READER_CLONE);
  CHECK(classifyReaderVersion(0x12) == READER_CLONE);
  CHECK(classifyReaderVersion(0x00) == READER_SILENT);
  CHECK(classifyReaderVersion(0xFF) == READER_SILENT);
  CHECK(classifyReaderVersion(0x55) == READER_UNEXPECTED);
}

void testCarRegistry() {
  CarRegistry cars;
  CHECK(cars.count() == 0);
  CHECK(cars.find(kCarA) == NO_CAR);

  CarRegistry::AddResult a = cars.add(kCarA);
  CHECK(a.status == CarRegistry::ADDED && a.car == 0);
  CHECK(cars.add(kCarB).car == 1);
  CHECK(cars.find(kCarA) == 0);
  CHECK(cars.find(kCarB) == 1);
  CHECK(cars.uidOf(1).equals(kCarB));

  // A partial read is refused and does not use a slot.
  CarRegistry::AddResult bad = cars.add(makeUid({0x04, 0xD1, 0x60, 0, 0, 0, 0}));
  CHECK(bad.status == CarRegistry::IMPLAUSIBLE && bad.car == NO_CAR);
  CHECK(cars.count() == 2);

  // E-25: a ninth car is refused; FULL wins over IMPLAUSIBLE.
  for (int i = 2; i < MAX_CARS; i++) {
    CHECK(cars.add(makeUid({0x04, i, 0x10, 0x20, 0x30, 0x40, 0x50})).status == CarRegistry::ADDED);
  }
  CHECK(cars.count() == MAX_CARS);
  CHECK(cars.add(makeUid({0x04, 0x99, 0x10, 0x20, 0x30, 0x40, 0x50})).status == CarRegistry::FULL);
  CHECK(cars.add(makeUid({0x04, 0, 0, 0})).status == CarRegistry::FULL);

  // Labels: truncated to TASK_LEN, stored byte for byte, blankable.
  CHECK(!cars.hasLabel(0));
  cars.setLabel(0, "abcdefghijklmnopqrstuvwxyz");
  CHECK_STR(cars.label(0), "abcdefghijklmnopqr");
  cars.setLabel(1, "caf\xC3\xA9");
  CHECK_STR(cars.label(1), "caf\xC3\xA9");
  cars.setLabel(1, "");
  CHECK(!cars.hasLabel(1));
  cars.setLabel(2, "x");
  cars.clearLabel(2);
  CHECK(!cars.hasLabel(2));
  cars.setLabel(3, "y");
  cars.clearAllLabels();
  CHECK(!cars.hasLabel(0) && !cars.hasLabel(3));
  CHECK(cars.count() == MAX_CARS);  // CLEAR keeps the UIDs

  // A car can be labelled before it is ever seen.
  CarRegistry fresh;
  fresh.setLabel(4, "early");
  CHECK_STR(fresh.label(4), "early");

#if !REMEMBER
  CHECK(fresh.load() == CarRegistry::LOAD_DISABLED);
  CHECK(!fresh.forget());
#endif
}

void testParkingLot() {
  CarRegistry cars;
  cars.add(kCarA);
  cars.add(kCarB);
  ParkingLot lot;
  for (byte s = 0; s < NUM_SPACES; s++) CHECK(lot.occupant(s) == NO_CAR);

  CHECK(lot.park(0, 0, 1000));
  CHECK(!lot.park(0, 0, 1100));  // same car re-landing: no change
  CHECK(lot.occupant(0) == 0);

  // E-26: car 0 moves from space 0 to space 1; the old space is released at once.
  CHECK(lot.park(1, 0, 1200));
  CHECK(lot.vacateElsewhere(0, 1) == 0x01);
  CHECK(lot.occupant(0) == NO_CAR && lot.occupant(1) == 0);
  CHECK(lot.vacateElsewhere(0, 1) == 0);
  CHECK(lot.vacateElsewhere(0, NO_CAR) == 0x02);  // pickup releases every space

  // E-28: one missed ping is not a departure; GONE_MS of silence is.
  lot.park(2, 1, 5000);
  CHECK(lot.updatePresence(2, false, 5000 + GONE_MS - 1) == NO_CAR);
  CHECK(lot.updatePresence(2, true, 5000 + GONE_MS) == NO_CAR);  // answered: timer restarts
  CHECK(lot.updatePresence(2, false, 5000 + 2 * GONE_MS - 1) == NO_CAR);
  CHECK(lot.updatePresence(2, false, 5000 + 2 * GONE_MS) == 1);
  CHECK(lot.occupant(2) == NO_CAR);

  // E-42: the timeout works across the millis() wrap.
  lot.park(3, 1, kNearWrap);
  CHECK(lot.updatePresence(3, false, kNearWrap + 100) == NO_CAR);
  CHECK(lot.updatePresence(3, false, kNearWrap + GONE_MS) == 1);

  // Rendering.
  char line[LCD_COLS + 1];
  ParkingLot view;
  view.renderLine(0, cars, line);
  CHECK_STR(line, "1>-");
  view.park(1, 1, 0);
  view.renderLine(1, cars, line);
  CHECK_STR(line, "2>CAR 2");
  cars.setLabel(1, "Email the Prof");
  view.renderLine(1, cars, line);
  CHECK_STR(line, "2>Email the Prof");
  cars.setLabel(1, "123456789012345678");
  view.renderLine(1, cars, line);
  CHECK_STR(line, "2>123456789012345678");
}

void testLaneDebouncer() {
  LaneDebouncer lane;
  CHECK(lane.accept(0, 1000));
  CHECK(!lane.accept(0, 1000 + LANE_COOLDOWN_MS - 1));  // E-09: same pass
  // The window slides while the car lingers.
  CHECK(!lane.accept(0, 1000 + 2 * LANE_COOLDOWN_MS - 2));
  CHECK(lane.accept(0, 1000 + 3 * LANE_COOLDOWN_MS));
  // A different car is always a new pass, even inside the window.
  CHECK(lane.accept(1, 1000 + 3 * LANE_COOLDOWN_MS + 1));
  CHECK(lane.accept(0, 1000 + 3 * LANE_COOLDOWN_MS + 2));

  LaneDebouncer wrap;
  CHECK(wrap.accept(2, kNearWrap));
  CHECK(!wrap.accept(2, kNearWrap + LANE_COOLDOWN_MS - 1));  // E-42
  CHECK(wrap.accept(2, kNearWrap + 3 * LANE_COOLDOWN_MS));
}

void testReadbackText() {
  ReadbackText text;
  CHECK(text.rowCount() == 0);

  text.append("Buy milk");
  text.append("and eggs");
  text.wrap();
  CHECK(text.rowCount() == 1);
  CHECK_STR(text.row(0), "Buy milk and eggs");

  // Break at the last space that fits, and drop it.
  text.clearAll();
  text.append("Email the professor about the poster");
  text.wrap();
  CHECK(text.rowCount() == 2);
  CHECK_STR(text.row(0), "Email the professor");
  CHECK_STR(text.row(1), "about the poster");

  // A word longer than a row is split.
  text.clearAll();
  text.append("Supercalifragilisticexpialidocious yes");
  text.wrap();
  CHECK_STR(text.row(0), "Supercalifragilistic");
  CHECK_STR(text.row(1), "expialidocious yes");

  // E-16: at most FULL_LEN characters and WRAP_LINES rows. 12-letter words fill one
  // row each, so 10 of them (capped at 120 characters) would need 10 rows.
  text.clearAll();
  for (int i = 0; i < 10; i++) text.append("abcdefghijkl");
  text.wrap();
  CHECK(text.rowCount() == WRAP_LINES);
  for (byte r = 0; r < text.rowCount(); r++) CHECK(strlen(text.row(r)) <= LCD_COLS);

  // FULLCLR keeps the rows on screen; CLEAR drops them.
  text.clearText();
  CHECK(text.rowCount() == WRAP_LINES);
  text.wrap();
  CHECK(text.rowCount() == 0);
  text.append("x");
  text.wrap();
  text.clearAll();
  CHECK(text.rowCount() == 0);
}

void testParse() {
  char buf[CMD_BUFFER_LEN];
  auto parse = [&](const char* line) {
    strcpy(buf, line);
    return SerialProtocol::parse(buf);
  };

  CHECK(parse("PING").kind == Command::CMD_PING);
  CHECK(parse("PINGX").kind == Command::CMD_PING);  // prefix match
  CHECK(parse("LOT").kind == Command::CMD_LOT);
  CHECK(parse("LOTS").kind == Command::CMD_LOT);
  CHECK(parse("FORGET").kind == Command::CMD_FORGET);
  CHECK(parse("CLEAR").kind == Command::CMD_CLEAR);
  CHECK(parse("FULLCLR").kind == Command::CMD_FULL_CLEAR);

  Command order = parse("ORDER 3");
  CHECK(order.kind == Command::CMD_ORDER && order.number == 3 && order.car() == 2);
  CHECK(parse("PLAY 8").kind == Command::CMD_PLAY);
  CHECK(parse("DONE 1").kind == Command::CMD_DONE);
  Command show = parse("FULLSHOW 2");
  CHECK(show.kind == Command::CMD_FULL_SHOW && show.car() == 1);

  Command full = parse("FULL hello there");
  CHECK(full.kind == Command::CMD_FULL_APPEND);
  CHECK_STR(full.text, "hello there");

  Command label = parse("CAR   4    Email   the Prof");
  CHECK(label.kind == Command::CMD_SET_LABEL && label.car() == 3);
  CHECK_STR(label.text, "Email   the Prof");
  Command blank = parse("CAR 4");
  CHECK(blank.kind == Command::CMD_SET_LABEL);
  CHECK_STR(blank.text, "");

  // E-34: numbers outside 1..MAX_CARS, and non-numbers (atoi reads 0).
  Command zero = parse("CAR 0 x");
  CHECK(zero.kind == Command::CMD_BAD_CAR && zero.number == 0);
  CHECK(parse("CAR 9 x").number == 9);
  CHECK(parse("ORDER abc").kind == Command::CMD_BAD_CAR);
  CHECK(parse("DONE -1").number == -1);
  CHECK(parse("FULLSHOW 99").kind == Command::CMD_BAD_CAR);

  // No space after the keyword: not that command.
  CHECK(parse("ORDER").kind == Command::CMD_UNKNOWN);
  CHECK(parse("FULLSHOW").kind == Command::CMD_UNKNOWN);
  Command unknown = parse("PARK 1 1");
  CHECK(unknown.kind == Command::CMD_UNKNOWN);
  CHECK_STR(unknown.text, "PARK 1 1");
  CHECK(parse("car 1 x").kind == Command::CMD_UNKNOWN);  // case-sensitive
}

void testReadLine() {
  SerialProtocol protocol(Serial);
  fake::serialTakeOutput();

  CHECK(protocol.readLine() == nullptr);
  fake::serialSend("PI");
  CHECK(protocol.readLine() == nullptr);  // partial line waits
  fake::serialSend("NG\r\n\n\r\nLOT\n");
  char* line = protocol.readLine();
  CHECK(line != nullptr);
  if (line) CHECK_STR(line, "PING");
  line = protocol.readLine();  // the empty lines are skipped
  CHECK(line != nullptr);
  if (line) CHECK_STR(line, "LOT");
  CHECK(protocol.readLine() == nullptr);

  // Truncated at CMD_BUFFER_LEN - 1, not rejected.
  std::string longLine(60, 'x');
  fake::serialSend(longLine + "\n");
  line = protocol.readLine();
  CHECK(line != nullptr);
  if (line) CHECK(strlen(line) == CMD_BUFFER_LEN - 1);
}

void testPrinters() {
  SerialProtocol protocol(Serial);
  fake::serialTakeOutput();

  protocol.printNewCar(0, makeUid({0x04, 0x0A, 0xFF}));
  CHECK_STR(fake::serialTakeOutput(), "* NEW CAR registered -> CAR 1   UID 04 0A FF \r\n");
  protocol.printParked(1, 2);
  CHECK_STR(fake::serialTakeOutput(), "SPACE 2  <- CAR 3 parked\r\n");
  protocol.printLeft(3, 7);
  CHECK_STR(fake::serialTakeOutput(), "SPACE 4  -> CAR 8 left\r\n");
  protocol.printOrdering(0);
  CHECK_STR(fake::serialTakeOutput(), "SPEAKER  CAR 1 ordering\r\n");
  protocol.printPlayback(0);
  CHECK_STR(fake::serialTakeOutput(), "PLAYBACK CAR 1 reading back\r\n");
  protocol.printCollected(0);
  CHECK_STR(fake::serialTakeOutput(), "PICKUP   CAR 1 collected\r\n");
  protocol.printTaskEcho(4, "");
  CHECK_STR(fake::serialTakeOutput(), "TASK 5 \r\n");  // trailing space is part of the format
  protocol.printBadCarNumber(-1);
  CHECK_STR(fake::serialTakeOutput(), "* bad car number: -1\r\n");
}

void testLcdView() {
  fake::setLcdAddress(LCD_ADDR_A);
  CarRegistry cars;
  cars.add(kCarA);
  ReadbackText text;
  OrderState order = {NO_CAR, NO_CAR};
  LcdView view(cars, text, order);
  CHECK(view.begin() == LCD_ADDR_A);

  // The lot, padded to the full width.
  view.setLotRow(0, "1>Email the Prof");
  view.setLotRow(1, "2>-");
  view.setLotRow(2, "3>-");
  view.setLotRow(3, "4>-");
  view.paint();
  CHECK_STR(fake::glassRow(0), "1>Email the Prof    ");

  // ORDER IN PROGRESS flashes the title only, every FLASH_SLOW_MS.
  uint32_t t = kNearWrap;  // and everything below crosses the millis() wrap (E-42)
  order.ordering = 0;
  view.showOrdering(t);
  view.paint();
  CHECK_STR(fake::glassRow(0), " ORDER IN PROGRESS  ");
  CHECK_STR(fake::glassRow(1), "       CAR 1        ");
  view.tick(t + FLASH_SLOW_MS - 1);
  CHECK_STR(fake::glassRow(0), " ORDER IN PROGRESS  ");
  view.tick(t + FLASH_SLOW_MS);
  CHECK_STR(fake::glassRow(0), "                    ");
  CHECK_STR(fake::glassRow(1), "       CAR 1        ");

  // An announcement covers everything, then gives the lot back after ANNOUNCE_MS.
  order.ordering = NO_CAR;
  view.announce("ORDER IS IN", t);
  CHECK(view.overlay() == LcdView::OV_ANNOUNCE);
  CHECK_STR(fake::glassRow(1), "    ORDER IS IN     ");
  view.tick(t + FLASH_FAST_MS);
  CHECK_STR(fake::glassRow(1), "                    ");
  view.tick(t + ANNOUNCE_MS);
  CHECK(view.overlay() == LcdView::OV_NONE);
  CHECK_STR(fake::glassRow(0), "1>Email the Prof    ");

  // A read-back with no full text shows the label; with text, pages of 3 rows.
  cars.setLabel(0, "Buy milk");
  order.playing = 0;
  view.startReadback(t);
  view.paint();
  CHECK_STR(fake::glassRow(0), "     YOUR ORDER     ");
  CHECK_STR(fake::glassRow(1), "      Buy milk      ");
  // Four words too long to share a row: four rows, so two pages.
  text.append("first-row-text");
  text.append("second-row-text");
  text.append("third-row-text");
  text.append("fourth-row-text");
  text.wrap();
  view.startFullTextReadback(t);
  view.paint();
  CHECK(text.rowCount() == 4);
  CHECK_STR(fake::glassRow(1), "first-row-text      ");
  CHECK_STR(fake::glassRow(3), "third-row-text      ");
  CHECK(!view.tick(t + PAGE_MS));
  CHECK_STR(fake::glassRow(1), "fourth-row-text     ");
  CHECK_STR(fake::glassRow(2), "                    ");
  // ...and times out after PLAY_MS.
  CHECK(!view.tick(t + PLAY_MS - 1));
  CHECK(view.tick(t + PLAY_MS));
  CHECK(view.overlay() == LcdView::OV_NONE);

  // A blank car's read-back says so.
  cars.clearLabel(0);
  text.clearAll();
  view.resumeReadback();
  view.paint();
  CHECK_STR(fake::glassRow(1), "     (no task)      ");
  view.closeReadback();
  CHECK(view.overlay() == LcdView::OV_NONE);
}

void testNoLcd() {
  fake::setLcdAddress(0);
  CarRegistry cars;
  ReadbackText text;
  OrderState order = {NO_CAR, NO_CAR};
  LcdView view(cars, text, order);
  CHECK(view.begin() == 0);  // E-40: no screen is not an error
  view.setLotRow(0, "1>-");
  view.paint();
  fake::setLcdAddress(LCD_ADDR_A);
}

struct Test {
  const char* name;
  void (*run)();
};

const Test kTests[] = {
    {"timing", testTiming},
    {"Uid", testUid},
    {"reader version", testReaderVersion},
    {"CarRegistry", testCarRegistry},
    {"ParkingLot", testParkingLot},
    {"LaneDebouncer", testLaneDebouncer},
    {"ReadbackText", testReadbackText},
    {"SerialProtocol::parse", testParse},
    {"SerialProtocol::readLine", testReadLine},
    {"SerialProtocol printers", testPrinters},
    {"LcdView", testLcdView},
    {"LcdView without an LCD", testNoLcd},
};

}  // namespace

/** Runs every test. Returns: 0 if all checks passed, 1 otherwise. */
int main() {
  for (const Test& test : kTests) {
    int before = gFailures;
    test.run();
    printf("  %s  %s\n", gFailures == before ? "PASS" : "FAIL", test.name);
  }
  printf("  %d checks, %d failed\n", gChecks, gFailures);
  return gFailures ? 1 : 0;
}
