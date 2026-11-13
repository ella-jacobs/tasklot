// SerialProtocol.h - the line protocol between the board and the laptop.
//
// Role: the only code that reads or writes the serial port. It turns incoming lines
// into Command values and prints every board event in its exact wire format.
//
// ** The printed strings are a contract. ** The laptop daemon, the browser simulator
// and the ears mock test parse them, including the spacing (two spaces after the space
// number and after SPEAKER, three after PICKUP, so the columns line up in a serial
// monitor). Change one and you must change the parsers in the same commit. The full
// table is in DESIGN.md section 3; firmware/tests/golden pins every byte.
//
// Commands are matched by prefix, in a fixed order, exactly as the original sketch did:
// PING, LOT, FORGET, "ORDER ", "PLAY ", FULLCLR, "FULLSHOW ", "FULL ", CLEAR, "DONE ",
// "CAR ". So "LOTS" acts as LOT and "PINGX" as PING.

#ifndef TASKLOT_SERIAL_PROTOCOL_H
#define TASKLOT_SERIAL_PROTOCOL_H

#include "CarRegistry.h"
#include "Uid.h"
#include "config.h"

/** One parsed command from the laptop. */
struct Command {
  // Prefixed: PING (and other short names) are AVR register macros on the Mega.
  enum Kind : byte {
    CMD_PING,         // -> PONG
    CMD_LOT,          // reprint the lot; ends a read-back
    CMD_FORGET,       // invalidate the EEPROM copy
    CMD_ORDER,        // act as if `car` passed the speaker
    CMD_PLAY,         // show car's read-back with no timeout
    CMD_FULL_CLEAR,   // empty the read-back text buffer
    CMD_FULL_SHOW,    // wrap the buffer and show it for `car`
    CMD_FULL_APPEND,  // append `text` to the read-back buffer
    CMD_CLEAR,        // blank every label
    CMD_DONE,         // blank car's label, close any order / read-back
    CMD_SET_LABEL,    // set car's label to `text`
    CMD_BAD_CAR,      // a car-numbered command with a number outside 1..MAX_CARS
    CMD_UNKNOWN,      // nothing matched; `text` is the whole line
  };

  Kind kind;
  // The car number exactly as sent (1-based) for commands that name one. For CMD_BAD_CAR it
  // is whatever atoi() made of the text, possibly 0 or negative, for the error message.
  int number;
  // FULL_APPEND / SET_LABEL: the text after the command; UNKNOWN: the whole line.
  // Points into the line buffer, so it is valid until the next readLine().
  const char* text;

  /** The named car as a 0-based index (valid unless kind is CMD_BAD_CAR). */
  int8_t car() const { return static_cast<int8_t>(number - 1); }
};

class SerialProtocol {
 public:
  /** Params: port - the serial port (already begun). */
  explicit SerialProtocol(HardwareSerial& port);

  // -------------------------------------------------------------------------
  // Input
  // -------------------------------------------------------------------------

  /**
   * Reads available bytes until a complete, non-empty line is in the buffer.
   *
   * \r is ignored, \n ends a line, empty lines are skipped. Bytes past
   * CMD_BUFFER_LEN - 1 are dropped (the line is truncated, not rejected).
   *
   * Returns: the line (NUL-terminated, valid until the next call), or nullptr when no
   *   complete line is waiting. Call repeatedly until nullptr to drain the port.
   */
  char* readLine();

  /**
   * Parses one line into a Command. Pure; does not touch the port.
   *
   * Params: line - a NUL-terminated line without its line ending.
   * Returns: the command; see Command::Kind for the prefix rules.
   */
  static Command parse(const char* line);

  // -------------------------------------------------------------------------
  // Events (board -> laptop). One method per line format in DESIGN.md 3.1.
  // Car and space parameters are 0-based; the wire shows them 1-based.
  // -------------------------------------------------------------------------

  /** "* NEW CAR registered -> CAR <n>   UID <hex> ... " */
  void printNewCar(int8_t car, const Uid& uid);
  /** "  no car slots left - reset the board to clear" */
  void printNoSlotsLeft();
  /** "* ignored a bad read (truncated UID): <hex> ... " followed by an empty line. */
  void printBadRead(const Uid& uid);
  /** "SPACE <s>  <- CAR <n> parked" */
  void printParked(byte space, int8_t car);
  /** "SPACE <s>  -> CAR <n> left" */
  void printLeft(byte space, int8_t car);
  /** "SPEAKER  CAR <n> ordering" */
  void printOrdering(int8_t car);
  /** "PLAYBACK CAR <n> reading back" */
  void printPlayback(int8_t car);
  /** "PICKUP   CAR <n> collected" */
  void printCollected(int8_t car);
  /** "TASK <n> <label>" (a blank label leaves a trailing space) */
  void printTaskEcho(int8_t car, const char* label);
  /** "PONG" */
  void printPong();
  /** "* tasks cleared" */
  void printTasksCleared();
  /** "* bad car number: <n>" with `number` as sent. */
  void printBadCarNumber(int number);
  /** "* unknown command: <line>" */
  void printUnknownCommand(const char* line);
  /** The FORGET reply; `remembered` is CarRegistry::forget()'s result. */
  void printForgetResult(bool remembered);
  /** The EEPROM line at boot (nothing when persistence is compiled out). */
  void printLoadResult(CarRegistry::LoadStatus status, byte count);

  /** The 20-dash rule that opens and closes every lot printout. */
  void printLotRule();
  /** One lot line, already rendered by ParkingLot::renderLine(). */
  void printLotLine(const char* line);

  // -------------------------------------------------------------------------
  // Boot banner
  // -------------------------------------------------------------------------

  /** Blank line, then the title. */
  void printBanner();
  /** "space <k> reader (SS <pin>): 0x<ver>   <verdict>" */
  void printSpaceReader(byte space, byte ssPin, byte version);
  /** "speaker reader (...)" or "pickup  reader (...)" */
  void printLaneReader(byte lane, byte ssPin, byte version);
  /** The starved-rail hint after the reader list. */
  void printRailHint();
  /** "LCD: 0x27" / "LCD: 0x3F", or the two no-LCD lines when `address` is 0. */
  void printLcdResult(byte address);
  /** The three help lines and a blank line. */
  void printHelp();

 private:
  // "<hex> <hex> ... " then the line ending; two uppercase digits per byte.
  void printUidBytes(const Uid& uid);
  // " reader (SS <pin>): 0x<ver>   <verdict>", shared by space and lane lines.
  void printReaderTail(byte ssPin, byte version);
  // "<before><n><after>" for the single-car events (SPEAKER, PLAYBACK, PICKUP).
  void printCarEvent(const __FlashStringHelper* before, int8_t car, const __FlashStringHelper* after);
  // "SPACE <s><arrow><n><after>" for parked / left.
  void printSpaceEvent(byte space, const __FlashStringHelper* arrow, int8_t car,
                       const __FlashStringHelper* after);

  HardwareSerial& port_;
  char line_[CMD_BUFFER_LEN];
  byte length_;
};

#endif  // TASKLOT_SERIAL_PROTOCOL_H
