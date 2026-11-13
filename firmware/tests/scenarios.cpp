// scenarios.cpp - drives the whole sketch through scripted sessions on the host and
// prints a transcript of everything the board said and showed.
//
// Role: the behaviour-preservation test for the firmware refactor. The sketch's own
// setup() and loop() run unchanged against the fakes in fakes/; this file places and
// removes tags, types serial commands, lets fake time pass, and records:
//
//   - every byte the board printed, with \r, \n and non-printable bytes escaped so
//     trailing spaces and line endings are visible, and
//   - the four LCD rows after every step.
//
// The transcripts in golden/ were produced by the monolithic sketch before the
// refactor (see regen_golden.sh). run_tests.sh builds this file against the current
// sketch and diffs its output against them, so any change in wire format or screen
// behaviour shows up as a diff.
//
// Usage (normally via run_tests.sh):
//   scenarios <name> [eeprom-file]
// The optional EEPROM file is loaded before boot and saved after the scenario, which
// is how the REMEMBER scenarios survive a "power cycle" between processes.

#include <Arduino.h>
#include <EEPROM.h>
#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <Wire.h>

#include <cstdio>
#include <functional>
#include <map>
#include <string>

// The sketch under test.
void setup();
void loop();

namespace {

// ---------------------------------------------------------------------------
// The physical deck, as the sketch's pin map defines it. These are duplicated here on
// purpose: the test pins the wiring, so a change to the pins in the sketch shows up.
// ---------------------------------------------------------------------------
const byte kSpace1 = 44;
const byte kSpace2 = 45;
const byte kSpace3 = 40;
const byte kSpace4 = 41;
const byte kSpeaker = 37;
const byte kPickup = 36;

// The loop runs about every 60 ms (delay(60) is the only thing that moves the fake
// clock), so waits are rounded up to whole passes.
const unsigned long kLoopMs = 60;

/** A tag UID as bytes. */
struct Tag {
  byte bytes[10];
  byte size;
};

// Nine plausible 7-byte NTAG213 UIDs (one more than MAX_CARS), plus the reads that
// the plausibility filter has to reject. The two truncated UIDs are the ones seen on
// the bench (DESIGN.md E-29).
const Tag kCars[9] = {
    {{0x04, 0xA1, 0x10, 0x2B, 0x7C, 0x51, 0x80}, 7},
    {{0x04, 0xB2, 0x21, 0x3C, 0x8D, 0x62, 0x80}, 7},
    {{0x04, 0xC3, 0x32, 0x4D, 0x9E, 0x73, 0x81}, 7},
    {{0x04, 0xD4, 0x43, 0x5E, 0xAF, 0x84, 0x81}, 7},
    {{0x04, 0xE5, 0x54, 0x6F, 0xB0, 0x95, 0x82}, 7},
    {{0x04, 0xF6, 0x65, 0x70, 0xC1, 0xA6, 0x82}, 7},
    {{0x04, 0x07, 0x76, 0x81, 0xD2, 0xB7, 0x83}, 7},
    {{0x04, 0x18, 0x87, 0x92, 0xE3, 0xC8, 0x83}, 7},
    {{0x04, 0x29, 0x98, 0xA3, 0xF4, 0xD9, 0x84}, 7},
};
const Tag kTruncatedA = {{0x04, 0xD1, 0x60, 0x00, 0x00, 0x00, 0x00}, 7};
const Tag kTruncatedB = {{0x04, 0xE1, 0x63, 0x00, 0x00, 0x00, 0x00}, 7};
const Tag kTrailingZeros = {{0x04, 0x5A, 0x6B, 0x7C, 0x8D, 0x00, 0x00}, 7};
const Tag kTooShort = {{0x04, 0x5A, 0x6B}, 3};
const Tag kFourByte = {{0x3A, 0x5B, 0x7C, 0x9D}, 4};

// ---------------------------------------------------------------------------
// Transcript helpers
// ---------------------------------------------------------------------------

/** Escapes bytes so the transcript is plain ASCII and line endings are visible. */
std::string escape(const std::string& raw) {
  std::string out;
  for (unsigned char c : raw) {
    if (c == '\r') {
      out += "\\r";
    } else if (c == '\n') {
      out += "\\n\n";
    } else if (c == '\\') {
      out += "\\\\";
    } else if (c < 0x20 || c > 0x7E) {
      char buf[8];
      snprintf(buf, sizeof(buf), "\\x%02X", c);
      out += buf;
    } else {
      out += static_cast<char>(c);
    }
  }
  return out;
}

/** Prints and clears what the board sent since the last flush. */
void flushSerial() {
  std::string out = fake::serialTakeOutput();
  if (out.empty()) return;
  std::string text = escape(out);
  // Every board line ends in \r\n, so each transcript line starts with the marker.
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) end = text.size() - 1;
    printf("  < %s\n", text.substr(start, end - start).c_str());
    start = end + 1;
  }
}

/** Prints the four LCD rows. */
void showGlass() {
  if (fake::glassRow(0).empty()) {
    printf("  [no LCD]\n");
    return;
  }
  for (int r = 0; r < 4; r++) printf("  |%s|\n", escape(fake::glassRow(r)).c_str());
}

/** Starts a new step in the transcript. */
void step(const char* what) {
  flushSerial();
  printf("-- %s (t=%lu)\n", what, millis());
}

/** Ends a step: board output, then the glass. */
void endStep() {
  flushSerial();
  showGlass();
}

// ---------------------------------------------------------------------------
// Actions. Each one runs one loop pass afterwards so the board sees the change.
// ---------------------------------------------------------------------------

void tick() { loop(); }

/** Lets about `ms` of board time pass, one loop pass at a time. */
void wait(unsigned long ms) {
  for (unsigned long t = 0; t < ms; t += kLoopMs) loop();
}

void place(byte pin, const Tag& tag) {
  fake::placeTag(pin, tag.bytes, tag.size);
  tick();
}

void lift(byte pin) {
  fake::removeTag(pin);
  tick();
}

void send(const std::string& line) {
  fake::serialSend(line);
  tick();
}

/** One labelled action: step header, the action, wait, then output and glass. */
void act(const char* what, const std::function<void()>& action, unsigned long thenWait = 0) {
  step(what);
  action();
  if (thenWait) wait(thenWait);
  endStep();
}

void boot() {
  step("boot");
  setup();
  endStep();
}

/** Registers car `index` by parking it on `pin` and leaves it there. */
void park(const char* what, byte pin, int index) {
  act(what, [&] { place(pin, kCars[index]); });
}

// ---------------------------------------------------------------------------
// Scenarios. Each runs in a fresh process, so every one starts from a cold boot.
// ---------------------------------------------------------------------------

void scenarioBoot() {
  fake::setMillis(5);
  boot();
  act("idle for a second", [] {}, 1000);
}

void scenarioBootDegraded() {
  fake::setLcdAddress(0);                  // no screen on the bus (E-40)
  fake::setReaderVersion(kSpace2, 0x00);   // not talking (E-41)
  fake::setReaderVersion(kSpace3, 0x12);   // clone
  fake::setReaderVersion(kSpace4, 0xFF);   // not talking
  fake::setReaderVersion(kSpeaker, 0x88);  // clone
  fake::setReaderVersion(kPickup, 0x55);   // unexpected but answering
  boot();
  park("car on space 1 with no LCD", kSpace1, 0);
}

void scenarioBootLcd3F() {
  fake::setLcdAddress(0x3F);
  boot();
}

void scenarioParkAndLeave() {
  boot();
  park("new car on space 1", kSpace1, 0);
  act("rest for half a second", [] {}, 500);
  act("lift for 0.6 s (under GONE_MS)", [] { lift(kSpace1); }, 600);
  act("put it back", [] { place(kSpace1, kCars[0]); }, 500);
  act("lift and wait 1.5 s", [] { lift(kSpace1); }, 1500);
  act("same car again on space 4", [] { place(kSpace4, kCars[0]); });
  park("second car on space 2", kSpace2, 1);
  act("lift both and wait", [] { lift(kSpace4); lift(kSpace2); }, 1500);
}

void scenarioMoveAndSwap() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  park("car 2 on space 3", kSpace3, 1);
  act("label both", [] {
    send("CAR 1 alpha\n");
    send("CAR 2 bravo\n");
  });
  act("move car 1 straight from space 1 to space 2 (E-26)",
      [] { lift(kSpace1); place(kSpace2, kCars[0]); }, 1500);
  act("fast swap of spaces 2 and 3 (both land inside GONE_MS)", [] {
    lift(kSpace2);
    lift(kSpace3);
    place(kSpace2, kCars[1]);
    place(kSpace3, kCars[0]);
  }, 1500);
  // After the fast swap car 2 is physically on space 2 and car 1 on space 3, but the
  // board still believes the opposite (presence pings do not check the UID).
  act("slow swap: lift both, wait, then set down swapped", [] {
    lift(kSpace2);
    lift(kSpace3);
    wait(1500);
    place(kSpace2, kCars[1]);
    place(kSpace3, kCars[0]);
  }, 500);
  act("fill spaces 1 and 4 too (E-24)", [] {
    place(kSpace1, kCars[2]);
    place(kSpace4, kCars[3]);
  }, 500);
}

void scenarioOrderFlow() {
  boot();
  act("blank car 1 at the speaker", [] { place(kSpeaker, kCars[0]); });
  act("ORDER IN PROGRESS, 0.5 s later", [] {}, 500);
  act("lift, re-present inside the cooldown (E-09)", [] {
    lift(kSpeaker);
    wait(300);
    place(kSpeaker, kCars[0]);
  }, 300);
  act("lift, wait past the cooldown, present again",
      [] { lift(kSpeaker); wait(2500); place(kSpeaker, kCars[0]); });
  act("park car 1 on space 1: order closes", [] { lift(kSpeaker); place(kSpace1, kCars[0]); });
  act("ORDER IS IN, 0.3 s in", [] {}, 300);
  act("announcement over", [] {}, 1500);
  act("laptop sends the label", [] { send("CAR 1 Email the Prof\n"); });
  act("move the labelled car: no announcement",
      [] { lift(kSpace1); place(kSpace2, kCars[0]); }, 500);
  act("blank car 2 orders", [] { place(kSpeaker, kCars[1]); });
  act("blank car 3 takes over the speaker (E-10)",
      [] { lift(kSpeaker); place(kSpeaker, kCars[2]); }, 200);
  act("car 2 parks while car 3 is ordering (E-11)",
      [] { lift(kSpeaker); place(kSpace3, kCars[1]); }, 2000);
}

void scenarioReadback() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  act("label it", [] { send("CAR 1 Buy milk\n"); });
  act("lift it and wait", [] { lift(kSpace1); }, 1500);
  act("labelled car 1 at the speaker", [] { place(kSpeaker, kCars[0]); }, 300);
  act("laptop sends the full text", [] {
    send("FULLCLR\n");
    send("FULL Buy milk and eggs and also the bread\n");
    send("FULL from the corner shop before it closes\n");
    send("FULL tonight at nine because tomorrow is a\n");
    send("FULL holiday and everything shuts early ok\n");
    send("FULLSHOW 1\n");
  });
  act("page 2", [] {}, 2500);
  act("page 3", [] {}, 2500);
  act("wraps to page 1", [] {}, 2500);
  act("12 s timeout", [] {}, 5000);
  act("PLAY 1 (no timeout)", [] { send("PLAY 1\n"); }, 13000);
  act("LOT ends it", [] { send("LOT\n"); });
  act("one long word wraps hard", [] {
    send("FULLCLR\n");
    send("FULL Supercalifragilisticexpialidocious yes\n");
    send("FULLSHOW 1\n");
  });
  act("park during the read-back ends it",
      [] { lift(kSpeaker); place(kSpace2, kCars[0]); }, 500);
  act("CLEAR, then PLAY a blank car", [] {
    send("CLEAR\n");
    send("PLAY 1\n");
  });
  act("LOT", [] { send("LOT\n"); });
  act("relabel and read back without full text (label only)", [] {
    send("CAR 1 Call the dentist\n");
    lift(kSpace2);
    wait(1500);
    place(kSpeaker, kCars[0]);
  }, 300);
  act("collect car 1 during its own read-back",
      [] { lift(kSpeaker); place(kPickup, kCars[0]); }, 2000);
}

void scenarioPickup() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  park("car 2 on space 2", kSpace2, 1);
  act("label car 1", [] { send("CAR 1 Task one\n"); });
  act("carry car 1 from space 1 to pickup", [] { lift(kSpace1); place(kPickup, kCars[0]); });
  act("ALL DONE!!, 0.3 s in", [] {}, 300);
  act("announcement over", [] {}, 1500);
  act("blank car 2 to pickup: no ALL DONE",
      [] { lift(kPickup); lift(kSpace2); place(kPickup, kCars[1]); }, 500);
  act("car 3 orders, then goes straight to pickup (E-12)", [] {
    lift(kPickup);
    place(kSpeaker, kCars[2]);
    wait(300);
    lift(kSpeaker);
    place(kPickup, kCars[2]);
  }, 500);
  act("car 4 orders; car 2 is collected meanwhile", [] {
    lift(kPickup);
    place(kSpeaker, kCars[3]);
    wait(300);
    place(kPickup, kCars[1]);
  }, 500);
  act("car 4 parks: order closes", [] { lift(kSpeaker); place(kSpace3, kCars[3]); }, 2000);
  act("car 1 lingers on pickup: one event", [] { lift(kPickup); place(kPickup, kCars[0]); }, 3000);
}

void scenarioCommands() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  act("PING / PINGX / LOTS", [] {
    send("PING\n");
    send("PINGX\n");
    send("LOTS\n");
  });
  act("bad car numbers (E-34)", [] {
    send("CAR 0 zero\n");
    send("CAR 9 nine\n");
    send("ORDER abc\n");
    send("DONE -1\n");
    send("PLAY 0\n");
    send("FULLSHOW 99\n");
  });
  act("prefix mismatches are unknown", [] {
    send("ORDER\n");
    send("FULLSHOW\n");
    send("car 1 lowercase\n");
    send("PARK 1 1\n");
    send("LEAVE 1\n");
    send("EMPTY\n");
  });
  act("over-long CAR line (truncated at 47, then 18)",
      [] { send("CAR 1 abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOP\n"); });
  act("extra spaces, CRLF, empty lines", [] {
    send("CAR   1    spaced   out\r\n");
    send("\n\r\n");
  });
  act("two commands in one burst", [] { send("PING\nLOT\n"); });
  act("non-ASCII bytes stored as-is (E-17)", [] { send("CAR 1 caf\xC3\xA9 \xE2\x80\x9Cq\xE2\x80\x9D\n"); });
  act("label a car never seen", [] { send("CAR 5 hello\n"); });
  act("CAR with no text blanks the label", [] { send("CAR 1\n"); });
  act("DONE on a labelled car", [] {
    send("CAR 1 finish me\n");
    send("DONE 1\n");
  }, 300);
  act("DONE on a blank car", [] { send("DONE 1\n"); }, 2000);
  act("ORDER 2 (blank) then DONE 2 while ordering", [] {
    send("ORDER 2\n");
    wait(300);
    send("DONE 2\n");
  }, 600);
  act("LOT after DONE", [] { send("LOT\n"); });
  act("ORDER on a labelled car becomes a read-back", [] {
    send("CAR 1 back again\n");
    send("ORDER 1\n");
  });
  act("FULL past 120 characters", [] {
    send("FULLCLR\n");
    send("FULL 0123456789012345678901234567890123456789\n");
    send("FULL abcdefghijabcdefghijabcdefghijabcdefghij\n");
    send("FULL ABCDEFGHIJABCDEFGHIJABCDEFGHIJABCDEFGHIJ\n");
    send("FULLSHOW 1\n");
  }, 5000);
  act("CLEAR", [] { send("CLEAR\n"); });
  act("FORGET", [] { send("FORGET\n"); });
}

void scenarioSlotsFull() {
  boot();
  act("truncated read (bench UID A)", [] { place(kSpace1, kTruncatedA); });
  act("truncated read (bench UID B)", [] { lift(kSpace1); place(kSpace1, kTruncatedB); });
  act("two trailing zeros", [] { lift(kSpace1); place(kSpace1, kTrailingZeros); });
  act("3-byte UID", [] { lift(kSpace1); place(kSpace1, kTooShort); });
  act("plausible 4-byte UID registers", [] { lift(kSpace1); place(kSpace1, kFourByte); });
  act("seven more cars fill the registry", [] {
    lift(kSpace1);
    wait(1500);
    for (int i = 0; i < 7; i++) {
      place(kSpace2, kCars[i]);
      lift(kSpace2);
      wait(1500);
    }
  });
  act("a ninth car on a space (E-25)", [] { place(kSpace3, kCars[7]); });
  act("a ninth car on a lane", [] { lift(kSpace3); place(kPickup, kCars[8]); });
  act("known cars still work", [] { lift(kPickup); place(kSpace4, kCars[0]); });
}

void scenarioPresenceOff() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  act("lift: no departure without presence", [] { lift(kSpace1); }, 2000);
  act("put back on space 1: nothing new", [] { place(kSpace1, kCars[0]); }, 300);
  act("car 1 on space 2 releases space 1", [] { lift(kSpace1); place(kSpace2, kCars[0]); });
  act("order with car 2 and re-land car 1 on space 2", [] {
    place(kSpeaker, kCars[1]);
    lift(kSpace2);
    place(kSpace2, kCars[0]);
  }, 2000);
  act("pickup releases the space", [] { lift(kSpace2); place(kPickup, kCars[0]); }, 500);
}

void scenarioRememberFirstBoot() {
  boot();
  park("car 1 on space 1", kSpace1, 0);
  park("car 2 on space 2", kSpace2, 1);
  act("label both", [] {
    send("CAR 1 saved one\n");
    send("CAR 2 saved two\n");
  });
}

void scenarioRememberSecondBoot() {
  boot();
  park("car 2 on space 3", kSpace3, 1);
  act("FORGET", [] { send("FORGET\n"); });
}

void scenarioRememberThirdBoot() {
  boot();
}

const std::map<std::string, void (*)()> kScenarios = {
    {"boot", scenarioBoot},
    {"boot_degraded", scenarioBootDegraded},
    {"boot_lcd_3f", scenarioBootLcd3F},
    {"park_and_leave", scenarioParkAndLeave},
    {"move_and_swap", scenarioMoveAndSwap},
    {"order_flow", scenarioOrderFlow},
    {"readback", scenarioReadback},
    {"pickup", scenarioPickup},
    {"commands", scenarioCommands},
    {"slots_full", scenarioSlotsFull},
    {"presence_off", scenarioPresenceOff},
    {"remember_1", scenarioRememberFirstBoot},
    {"remember_2", scenarioRememberSecondBoot},
    {"remember_3", scenarioRememberThirdBoot},
};

}  // namespace

/**
 * Runs one scenario and prints its transcript to stdout.
 *
 * Params: argv[1] - scenario name; argv[2] - optional EEPROM image file, loaded before
 *   boot and written back afterwards.
 * Returns: 0 on success, 2 for an unknown scenario or bad usage.
 */
int main(int argc, char** argv) {
  if (argc < 2 || !kScenarios.count(argv[1])) {
    fprintf(stderr, "usage: %s <scenario> [eeprom-file]\nscenarios:", argv[0]);
    for (const auto& s : kScenarios) fprintf(stderr, " %s", s.first.c_str());
    fprintf(stderr, "\n");
    return 2;
  }
  const char* eeprom = argc > 2 ? argv[2] : nullptr;
  if (eeprom) fake::eepromLoad(eeprom);

  printf("=== %s\n", argv[1]);
  kScenarios.at(argv[1])();
  flushSerial();
  if (eeprom) fake::eepromSave(eeprom);
  return 0;
}
