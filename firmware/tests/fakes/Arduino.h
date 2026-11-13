// Arduino.h (host fake) - the slice of the Arduino core the TaskLot sketch uses,
// reimplemented for a laptop so the firmware can be compiled and exercised with the
// system C++ compiler.
//
// Role: lets firmware/tests build the real sketch sources unchanged. Only the
// behaviour the sketch can observe is modelled: a controllable clock, a serial port
// with a scripted input queue and a captured output buffer, and the Print number
// formatting rules. Pin I/O is accepted and ignored.
//
// Used by: every file in firmware/tests. Never compiled for the board.

#ifndef TASKLOT_FAKE_ARDUINO_H
#define TASKLOT_FAKE_ARDUINO_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <string>

typedef uint8_t byte;
typedef bool boolean;

#define HIGH   1
#define LOW    0
#define INPUT  0
#define OUTPUT 1

// Matches the Mega 2560 core, where A0 is digital pin 54.
#define A0 54

#define DEC 10
#define HEX 16

// On AVR, F() moves a string literal into flash and tags it with this type so the
// right print() overload reads it back. On the host the pointer is an ordinary
// const char*, so the tag is a cast and nothing more.
class __FlashStringHelper;
#define F(literal) (reinterpret_cast<const __FlashStringHelper*>(literal))

/**
 * Milliseconds since "boot", from the fake clock.
 *
 * Returns: the clock as a 32-bit value widened to unsigned long. The clock is kept
 *   in 32 bits so it wraps exactly like the ATmega's millis() (about 49.7 days),
 *   even though unsigned long is 64 bits on the host.
 */
unsigned long millis();

/**
 * Blocks for `ms` milliseconds. On the host this advances the fake clock and returns.
 *
 * Side effects: moves the fake clock forward by `ms`.
 */
void delay(unsigned long ms);

/** Accepted and ignored; the fakes do not model GPIO. */
void pinMode(uint8_t pin, uint8_t mode);

/** Accepted and ignored; the fakes do not model GPIO. */
void digitalWrite(uint8_t pin, uint8_t value);

/**
 * Print - the Arduino formatting base class, reduced to the overloads the sketch calls.
 *
 * Subclasses implement write(uint8_t). Number formatting follows the Arduino core:
 * base 10 prints a leading '-' for negatives, base 16 prints uppercase digits with no
 * prefix and no padding, and print(unsigned char) prints a number, not a character.
 */
class Print {
 public:
  virtual ~Print() {}

  /** Writes one byte. Returns the number of bytes written (1). */
  virtual size_t write(uint8_t c) = 0;

  size_t write(const char* s);

  size_t print(const __FlashStringHelper* s);
  size_t print(const char* s);
  size_t print(char c);
  size_t print(unsigned char n, int base = DEC);
  size_t print(int n, int base = DEC);
  size_t print(unsigned int n, int base = DEC);
  size_t print(long n, int base = DEC);
  size_t print(unsigned long n, int base = DEC);

  size_t println();
  size_t println(const __FlashStringHelper* s);
  size_t println(const char* s);
  size_t println(char c);
  size_t println(unsigned char n, int base = DEC);
  size_t println(int n, int base = DEC);
  size_t println(unsigned int n, int base = DEC);
  size_t println(long n, int base = DEC);
  size_t println(unsigned long n, int base = DEC);

 private:
  size_t printNumber(unsigned long n, int base);
};

/**
 * HardwareSerial - USB serial with a scripted receive queue and a captured transmit log.
 *
 * Tests push bytes with fake::serialSend() and read what the sketch printed with
 * fake::serialTakeOutput().
 */
class HardwareSerial : public Print {
 public:
  void begin(unsigned long baud);
  int available();
  int read();
  size_t write(uint8_t c) override;
  using Print::write;
};

extern HardwareSerial Serial;

namespace fake {

/** Sets the fake clock (milliseconds). Used to start a scenario near the wrap. */
void setMillis(uint32_t ms);

/** Queues `text` on the serial receive line, byte for byte. */
void serialSend(const std::string& text);

/** Returns everything the sketch printed since the last call, and clears it. */
std::string serialTakeOutput();

}  // namespace fake

#endif  // TASKLOT_FAKE_ARDUINO_H
