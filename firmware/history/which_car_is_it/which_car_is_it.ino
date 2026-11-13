// TaskLot - car recognition test  [ARDUINO MEGA wiring]
// Tap a new sticker   -> it gets registered as the next car
// Tap a known sticker -> it says which car it already is
// This is the whole identity system for the project, in one file.
//
// WIRING - Arduino Mega 2560:
//   RC522 3.3V -> 3.3V   ** NEVER 5V - it kills the board **
//   RC522 GND  -> GND
//   RC522 RST  -> A5
//   RC522 SDA  -> 44     (also labelled SS)
//   RC522 SCK  -> 52
//   RC522 MOSI -> 51
//   RC522 MISO -> 50
//   RC522 IRQ  -> not connected
//
// Note: you never declare SCK/MOSI/MISO in code. On the Mega those are
// the fixed hardware SPI pins (52/51/50) and SPI.begin() claims them
// automatically. Only SS and RST need naming below - and SS can be any free pin,
// which is why it's 44 here.

#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN A5
#define SS_PIN  44

MFRC522 mfrc522(SS_PIN, RST_PIN);

const byte MAX_CARS = 6;
byte known[MAX_CARS][10];   // stored UIDs
byte knownLen[MAX_CARS];    // how many bytes each UID is
byte carCount = 0;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();
  Serial.println(F("=== TaskLot car recognition ==="));
  Serial.println(F("Tap each sticker. New ones get a car number."));
  Serial.println();
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  if (!mfrc522.PICC_ReadCardSerial()) return;

  int car = findCar();

  if (car >= 0) {
    Serial.print(F("  recognized  -> CAR "));
    Serial.println(car + 1);
  } else {
    car = addCar();
    if (car < 0) {
      Serial.println(F("  no slots left - restart to clear"));
    } else {
      Serial.print(F("* NEW CAR registered -> CAR "));
      Serial.println(car + 1);
    }
  }

  mfrc522.PICC_HaltA();
  delay(800);   // stops one tap registering ten times
}

// Do we already know this UID?
int findCar() {
  for (byte i = 0; i < carCount; i++) {
    if (knownLen[i] != mfrc522.uid.size) continue;
    bool same = true;
    for (byte b = 0; b < knownLen[i]; b++) {
      if (known[i][b] != mfrc522.uid.uidByte[b]) { same = false; break; }
    }
    if (same) return i;
  }
  return -1;
}

// Remember a UID we've never seen before
int addCar() {
  if (carCount >= MAX_CARS) return -1;
  knownLen[carCount] = mfrc522.uid.size;
  for (byte b = 0; b < mfrc522.uid.size; b++) {
    known[carCount][b] = mfrc522.uid.uidByte[b];
  }
  carCount++;
  return carCount - 1;
}
