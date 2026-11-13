// SerialProtocol.cpp - command parsing and the exact event strings. See SerialProtocol.h.
//
// Every string here is in F() so it stays in flash: the Mega has 8 KB of SRAM and the
// boot banner alone would take a large share of it.

#include "SerialProtocol.h"

#include "RfidSlot.h"

namespace {

/**
 * Matches a command keyword at the start of a line.
 *
 * Params: line - the whole line; prefix - the keyword, including its trailing space
 *   when the command takes an argument.
 * Returns: a pointer just past the prefix if the line starts with it, else nullptr.
 */
const char* afterPrefix(const char* line, const char* prefix) {
  size_t n = strlen(prefix);
  return strncmp(line, prefix, n) == 0 ? line + n : nullptr;
}

/**
 * Validates the car number at the start of `rest`.
 *
 * Params: rest - the text after the keyword; kind - the command kind when valid.
 * Returns: {kind, n} for 1 <= n <= MAX_CARS, otherwise {CMD_BAD_CAR, n}. atoi() reads
 *   a non-number as 0, so "ORDER abc" is CMD_BAD_CAR 0.
 */
Command carCommand(const char* rest, Command::Kind kind) {
  int n = atoi(rest);
  if (n < 1 || n > MAX_CARS) return {Command::CMD_BAD_CAR, n, nullptr};
  return {kind, n, nullptr};
}

/** Skips spaces. Returns: the first non-space character of `p`. */
const char* skipSpaces(const char* p) {
  while (*p == ' ') p++;
  return p;
}

}  // namespace

SerialProtocol::SerialProtocol(HardwareSerial& port) : port_(port), length_(0) {
  line_[0] = '\0';
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------

char* SerialProtocol::readLine() {
  while (port_.available()) {
    char c = static_cast<char>(port_.read());
    if (c == '\r') continue;
    if (c == '\n') {
      line_[length_] = '\0';
      bool complete = length_ > 0;
      length_ = 0;
      if (complete) return line_;
      continue;
    }
    if (length_ < CMD_BUFFER_LEN - 1) line_[length_++] = c;
  }
  return nullptr;
}

Command SerialProtocol::parse(const char* line) {
  // The order matters: it is the order the original sketch tested prefixes in, and
  // "FULLSHOW " must be tried before "FULL ".
  const char* rest;
  if (afterPrefix(line, "PING")) return {Command::CMD_PING, 0, nullptr};
  if (afterPrefix(line, "LOT")) return {Command::CMD_LOT, 0, nullptr};
  if (afterPrefix(line, "FORGET")) return {Command::CMD_FORGET, 0, nullptr};
  if ((rest = afterPrefix(line, "ORDER "))) return carCommand(rest, Command::CMD_ORDER);
  if ((rest = afterPrefix(line, "PLAY "))) return carCommand(rest, Command::CMD_PLAY);
  if (afterPrefix(line, "FULLCLR")) return {Command::CMD_FULL_CLEAR, 0, nullptr};
  if ((rest = afterPrefix(line, "FULLSHOW "))) return carCommand(rest, Command::CMD_FULL_SHOW);
  if ((rest = afterPrefix(line, "FULL "))) return {Command::CMD_FULL_APPEND, 0, rest};
  if (afterPrefix(line, "CLEAR")) return {Command::CMD_CLEAR, 0, nullptr};
  if ((rest = afterPrefix(line, "DONE "))) return carCommand(rest, Command::CMD_DONE);

  if ((rest = afterPrefix(line, "CAR "))) {
    // CAR <n> <text>: spaces, the number, the rest of that word, spaces, then the text.
    const char* p = skipSpaces(rest);
    Command cmd = carCommand(p, Command::CMD_SET_LABEL);
    while (*p && *p != ' ') p++;
    if (cmd.kind == Command::CMD_SET_LABEL) cmd.text = skipSpaces(p);
    return cmd;
  }

  return {Command::CMD_UNKNOWN, 0, line};
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

void SerialProtocol::printUidBytes(const Uid& uid) {
  for (byte i = 0; i < uid.size; i++) {
    if (uid.bytes[i] < 0x10) port_.print('0');  // always two hex digits
    port_.print(uid.bytes[i], HEX);
    port_.print(' ');
  }
  port_.println();
}

void SerialProtocol::printCarEvent(const __FlashStringHelper* before, int8_t car,
                                   const __FlashStringHelper* after) {
  port_.print(before);
  port_.print(car + 1);
  port_.println(after);
}

void SerialProtocol::printSpaceEvent(byte space, const __FlashStringHelper* arrow, int8_t car,
                                     const __FlashStringHelper* after) {
  port_.print(F("SPACE "));
  port_.print(space + 1);
  port_.print(arrow);
  port_.print(car + 1);
  port_.println(after);
}

void SerialProtocol::printNewCar(int8_t car, const Uid& uid) {
  port_.print(F("* NEW CAR registered -> CAR "));
  port_.print(car + 1);
  port_.print(F("   UID "));
  printUidBytes(uid);
}

void SerialProtocol::printNoSlotsLeft() {
  port_.println(F("  no car slots left - reset the board to clear"));
}

void SerialProtocol::printBadRead(const Uid& uid) {
  port_.print(F("* ignored a bad read (truncated UID): "));
  printUidBytes(uid);
  port_.println();
}

void SerialProtocol::printParked(byte space, int8_t car) {
  printSpaceEvent(space, F("  <- CAR "), car, F(" parked"));
}

void SerialProtocol::printLeft(byte space, int8_t car) {
  printSpaceEvent(space, F("  -> CAR "), car, F(" left"));
}

void SerialProtocol::printOrdering(int8_t car) {
  printCarEvent(F("SPEAKER  CAR "), car, F(" ordering"));
}

void SerialProtocol::printPlayback(int8_t car) {
  printCarEvent(F("PLAYBACK CAR "), car, F(" reading back"));
}

void SerialProtocol::printCollected(int8_t car) {
  printCarEvent(F("PICKUP   CAR "), car, F(" collected"));
}

void SerialProtocol::printTaskEcho(int8_t car, const char* label) {
  port_.print(F("TASK "));
  port_.print(car + 1);
  port_.print(' ');
  port_.println(label);
}

void SerialProtocol::printPong() { port_.println(F("PONG")); }

void SerialProtocol::printTasksCleared() { port_.println(F("* tasks cleared")); }

void SerialProtocol::printBadCarNumber(int number) {
  port_.print(F("* bad car number: "));
  port_.println(number);
}

void SerialProtocol::printUnknownCommand(const char* line) {
  port_.print(F("* unknown command: "));
  port_.println(line);
}

void SerialProtocol::printForgetResult(bool remembered) {
  if (remembered) {
    port_.println(F("* EEPROM forgotten - reset the board to start clean"));
  } else {
    port_.println(F("* REMEMBER is off - nothing is saved"));
  }
}

void SerialProtocol::printLoadResult(CarRegistry::LoadStatus status, byte count) {
  switch (status) {
    case CarRegistry::LOAD_NOTHING_SAVED:
      port_.println(F("EEPROM: nothing saved yet"));
      return;
    case CarRegistry::LOAD_BAD_COUNT:
      port_.println(F("EEPROM: bad count, ignoring"));
      return;
    case CarRegistry::LOAD_RESTORED:
      port_.print(F("EEPROM: restored "));
      port_.print(count);
      port_.println(F(" car(s) and their tasks"));
      return;
    case CarRegistry::LOAD_DISABLED:
    default:
      return;
  }
}

// 20 dashes = the LCD's width. The laptop's pacing counts two of these as "the command
// finished", so the rule must open and close every printout.
void SerialProtocol::printLotRule() { port_.println(F("--------------------")); }

void SerialProtocol::printLotLine(const char* line) { port_.println(line); }

// ---------------------------------------------------------------------------
// Boot banner
// ---------------------------------------------------------------------------

void SerialProtocol::printBanner() {
  port_.println();
  port_.println(F("=== TaskLot v2 - four spaces, a speaker, a pickup lane ==="));
}

void SerialProtocol::printReaderTail(byte ssPin, byte version) {
  port_.print(F(" reader (SS "));
  port_.print(ssPin);
  port_.print(F("): 0x"));
  if (version < 0x10) port_.print('0');
  port_.print(version, HEX);
  switch (classifyReaderVersion(version)) {
    case READER_SILENT:
      port_.println(F("   <-- NOT TALKING"));
      return;
    case READER_GENUINE:
      port_.println(F("   ok - genuine"));
      return;
    case READER_CLONE:
      port_.println(F("   ok - clone"));
      return;
    case READER_UNEXPECTED:
    default:
      port_.println(F("   ?? unexpected, but answering"));
      return;
  }
}

void SerialProtocol::printSpaceReader(byte space, byte ssPin, byte version) {
  port_.print(F("space "));
  port_.print(space + 1);
  printReaderTail(ssPin, version);
}

void SerialProtocol::printLaneReader(byte lane, byte ssPin, byte version) {
  port_.print(lane == LANE_SPEAKER ? F("speaker") : F("pickup "));  // same width
  printReaderTail(ssPin, version);
}

void SerialProtocol::printRailHint() {
  port_.println(F("(good versions but no tag reads = starved 3.3V rail, not wiring)"));
}

void SerialProtocol::printLcdResult(byte address) {
  if (!address) {
    port_.println(F("LCD: none found. Check 5V, GND, SDA->20, SCL->21."));
    port_.println(F("     Readers still work; the lot prints to Serial only."));
    return;
  }
  port_.print(F("LCD: 0x"));
  port_.println(address, HEX);
}

void SerialProtocol::printHelp() {
  port_.println(F("Drive past the SPEAKER to order. PARK to finish the order."));
  port_.println(F("Drive through PICKUP when the task is done."));
  port_.println(F("Send: CAR <n> <text> | DONE <n> | CLEAR | LOT | PING"));
  port_.println();
}
