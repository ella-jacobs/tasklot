// SPI.h (host fake) - the SPI bus object the sketch starts at boot.
//
// Role: lets the sketch call SPI.begin() on the host. The fake MFRC522 readers do not
// talk over a bus, so there is nothing to model. Used by firmware/tests only.

#ifndef TASKLOT_FAKE_SPI_H
#define TASKLOT_FAKE_SPI_H

/** The hardware SPI bus. begin() is accepted and ignored. */
class SPIClass {
 public:
  void begin() {}
};

extern SPIClass SPI;

#endif  // TASKLOT_FAKE_SPI_H
