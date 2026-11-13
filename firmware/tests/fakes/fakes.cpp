// fakes.cpp - definitions behind the host fakes in this folder (Arduino core, SPI,
// Wire, EEPROM, MFRC522, LiquidCrystal_I2C).
//
// Role: one translation unit holding all the fake hardware state, so every test binary
// links the same behaviour. All state is file-local and reached through the fake::
// functions declared in the headers. Used by firmware/tests only.

#include <Arduino.h>
#include <EEPROM.h>
#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <SPI.h>
#include <Wire.h>

#include <deque>
#include <fstream>
#include <map>

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

namespace {
// 32 bits on purpose: the ATmega's millis() is a 32-bit counter, and the wrap tests
// depend on it rolling over at 2^32 here too.
uint32_t gClockMs = 0;
}  // namespace

unsigned long millis() { return gClockMs; }
void delay(unsigned long ms) { gClockMs += static_cast<uint32_t>(ms); }
void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t, uint8_t) {}

void fake::setMillis(uint32_t ms) { gClockMs = ms; }

// ---------------------------------------------------------------------------
// Print
// ---------------------------------------------------------------------------

size_t Print::write(const char* s) {
  size_t n = 0;
  while (*s) n += write(static_cast<uint8_t>(*s++));
  return n;
}

size_t Print::print(const __FlashStringHelper* s) {
  return write(reinterpret_cast<const char*>(s));
}
size_t Print::print(const char* s) { return write(s); }
size_t Print::print(char c) { return write(static_cast<uint8_t>(c)); }
size_t Print::print(unsigned char n, int base) { return printNumber(n, base); }
size_t Print::print(unsigned int n, int base) { return printNumber(n, base); }
size_t Print::print(unsigned long n, int base) { return printNumber(n, base); }
size_t Print::print(int n, int base) { return print(static_cast<long>(n), base); }

size_t Print::print(long n, int base) {
  // Arduino prints a sign only in base 10; other bases print the two's-complement
  // bits. The sketch only ever prints non-negative hex, so only the DEC rule matters.
  if (base == DEC && n < 0) return write('-') + printNumber(static_cast<unsigned long>(-n), DEC);
  return printNumber(static_cast<unsigned long>(n), base);
}

size_t Print::printNumber(unsigned long n, int base) {
  char buf[8 * sizeof(unsigned long) + 1];
  char* p = &buf[sizeof(buf) - 1];
  *p = '\0';
  do {
    int digit = static_cast<int>(n % base);
    *--p = static_cast<char>(digit < 10 ? '0' + digit : 'A' + digit - 10);
    n /= base;
  } while (n);
  return write(p);
}

size_t Print::println() { return write("\r\n"); }
size_t Print::println(const __FlashStringHelper* s) { return print(s) + println(); }
size_t Print::println(const char* s) { return print(s) + println(); }
size_t Print::println(char c) { return print(c) + println(); }
size_t Print::println(unsigned char n, int base) { return print(n, base) + println(); }
size_t Print::println(int n, int base) { return print(n, base) + println(); }
size_t Print::println(unsigned int n, int base) { return print(n, base) + println(); }
size_t Print::println(long n, int base) { return print(n, base) + println(); }
size_t Print::println(unsigned long n, int base) { return print(n, base) + println(); }

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------

HardwareSerial Serial;

namespace {
std::deque<char> gSerialIn;
std::string gSerialOut;
}  // namespace

void HardwareSerial::begin(unsigned long) {}
int HardwareSerial::available() { return static_cast<int>(gSerialIn.size()); }

int HardwareSerial::read() {
  if (gSerialIn.empty()) return -1;
  char c = gSerialIn.front();
  gSerialIn.pop_front();
  return static_cast<unsigned char>(c);
}

size_t HardwareSerial::write(uint8_t c) {
  gSerialOut.push_back(static_cast<char>(c));
  return 1;
}

void fake::serialSend(const std::string& text) {
  for (char c : text) gSerialIn.push_back(c);
}

std::string fake::serialTakeOutput() {
  std::string out;
  out.swap(gSerialOut);
  return out;
}

// ---------------------------------------------------------------------------
// SPI and Wire
// ---------------------------------------------------------------------------

SPIClass SPI;
TwoWire Wire;

namespace {
uint8_t gLcdAddress = 0x27;
}  // namespace

uint8_t TwoWire::endTransmission() {
  return (gLcdAddress != 0 && probing_ == gLcdAddress) ? 0 : 2;
}

void fake::setLcdAddress(uint8_t address) { gLcdAddress = address; }

// ---------------------------------------------------------------------------
// EEPROM
// ---------------------------------------------------------------------------

EEPROMClass EEPROM;

namespace {
const int kEepromSize = 4096;  // ATmega2560
uint8_t gEeprom[kEepromSize];
bool gEepromErased = false;

uint8_t* eepromCell(int address) {
  if (!gEepromErased) {
    memset(gEeprom, 0xFF, sizeof(gEeprom));  // a new chip reads all ones
    gEepromErased = true;
  }
  return (address >= 0 && address < kEepromSize) ? &gEeprom[address] : nullptr;
}
}  // namespace

uint8_t EEPROMClass::read(int address) {
  uint8_t* cell = eepromCell(address);
  return cell ? *cell : 0xFF;
}

void EEPROMClass::write(int address, uint8_t value) {
  uint8_t* cell = eepromCell(address);
  if (cell) *cell = value;
}

void EEPROMClass::update(int address, uint8_t value) {
  if (read(address) != value) write(address, value);
}

void fake::eepromLoad(const char* path) {
  eepromCell(0);
  std::ifstream in(path, std::ios::binary);
  if (in) in.read(reinterpret_cast<char*>(gEeprom), kEepromSize);
}

void fake::eepromSave(const char* path) {
  eepromCell(0);
  std::ofstream out(path, std::ios::binary);
  out.write(reinterpret_cast<const char*>(gEeprom), kEepromSize);
}

// ---------------------------------------------------------------------------
// MFRC522
// ---------------------------------------------------------------------------

namespace {

/** One reader's field: the tag in it (if any) and the reader's version byte. */
struct Field {
  bool present = false;
  bool halted = false;
  MFRC522::Uid tag = {0, {0}, 0};
  byte version = 0x92;  // "ok - genuine"
};

std::map<byte, Field>& fields() {
  static std::map<byte, Field> f;  // function-local: safe during static init
  return f;
}

}  // namespace

MFRC522::MFRC522(byte chipSelectPin, byte) : ss_(chipSelectPin) {
  uid = {0, {0}, 0};
  fields()[ss_];
}

byte MFRC522::PCD_ReadRegister(PCD_Register) { return fields()[ss_].version; }

bool MFRC522::PICC_IsNewCardPresent() {
  const Field& f = fields()[ss_];
  return f.present && !f.halted;
}

bool MFRC522::PICC_ReadCardSerial() {
  const Field& f = fields()[ss_];
  if (!f.present) return false;
  uid = f.tag;
  return true;
}

MFRC522::StatusCode MFRC522::PICC_HaltA() {
  Field& f = fields()[ss_];
  if (f.present) f.halted = true;
  return STATUS_OK;
}

MFRC522::StatusCode MFRC522::PICC_WakeupA(byte*, byte*) {
  Field& f = fields()[ss_];
  if (!f.present) return STATUS_TIMEOUT;
  f.halted = false;
  return STATUS_OK;
}

void fake::placeTag(byte ssPin, const byte* uid, byte size) {
  Field& f = fields()[ssPin];
  f.present = true;
  f.halted = false;
  f.tag.size = size;
  memset(f.tag.uidByte, 0, sizeof(f.tag.uidByte));
  memcpy(f.tag.uidByte, uid, size);
}

void fake::removeTag(byte ssPin) {
  Field& f = fields()[ssPin];
  f.present = false;
  f.halted = false;
}

void fake::setReaderVersion(byte ssPin, byte version) { fields()[ssPin].version = version; }

// ---------------------------------------------------------------------------
// LiquidCrystal_I2C
// ---------------------------------------------------------------------------

namespace {
const int kGlassCols = 20;
const int kGlassRows = 4;
char gGlass[kGlassRows][kGlassCols];
bool gGlassOn = false;
int gCursorCol = 0;
int gCursorRow = 0;
}  // namespace

void LiquidCrystal_I2C::init() {
  gGlassOn = true;
  clear();
}

void LiquidCrystal_I2C::clear() {
  memset(gGlass, ' ', sizeof(gGlass));
  gCursorCol = 0;
  gCursorRow = 0;
}

void LiquidCrystal_I2C::setCursor(uint8_t col, uint8_t row) {
  gCursorCol = col;
  gCursorRow = row;
}

size_t LiquidCrystal_I2C::write(uint8_t c) {
  if (gCursorRow < kGlassRows && gCursorCol < kGlassCols) {
    gGlass[gCursorRow][gCursorCol] = static_cast<char>(c);
  }
  gCursorCol++;
  return 1;
}

std::string fake::glassRow(int row) {
  if (!gGlassOn || row < 0 || row >= kGlassRows) return "";
  return std::string(gGlass[row], kGlassCols);
}
