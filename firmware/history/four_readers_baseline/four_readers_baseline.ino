#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN A0  // Reset pin for all readers
#define SS_PIN2 45 // Slave Select pin for RFID reader 1
#define SS_PIN1 44 // Slave Select pin for RFID reader 2
#define SS_PIN3 40 // Slave Select pin for RFID reader 3
#define SS_PIN4 41 // Slave Select pin for RFID reader 4
#define SS_PIN5 36 // Slave Select pin for RFID reader 5
#define SS_PIN6 37 // Slave Select pin for RFID reader 6
// Add more SS pins if using more readers

MFRC522 rfid1(SS_PIN1, RST_PIN);  // Create an instance for RFID reader 1
MFRC522 rfid2(SS_PIN2, RST_PIN);  // Create an instance for RFID reader 2
MFRC522 rfid3(SS_PIN3, RST_PIN);  // Create an instance for RFID reader 3
MFRC522 rfid4(SS_PIN4, RST_PIN);  // Create an instance for RFID reader 4
MFRC522 rfid5(SS_PIN5, RST_PIN);  // Create an instance for RFID reader 5
MFRC522 rfid6(SS_PIN6, RST_PIN);  // Create an instance for RFID reader 6

void setup() {
  Serial.begin(9600);   // Initialize serial communications
  SPI.begin();          // Initialize SPI bus

  rfid1.PCD_Init();     // Initialize RFID reader 1
  rfid2.PCD_Init();     // Initialize RFID reader 2
  rfid3.PCD_Init();     // Initialize RFID reader 3
  rfid4.PCD_Init();     // Initialize RFID reader 4
  rfid5.PCD_Init();     // Initialize RFID reader 5
  rfid6.PCD_Init();     // Initialize RFID reader 6
  
  Serial.println("Multiple RFID Readers ready.");
}

void loop() {
  // Handle RFID reader 1
  if (rfid1.PICC_IsNewCardPresent() && rfid1.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 1: ");
    rfid1.PICC_HaltA();}
  if (rfid2.PICC_IsNewCardPresent() && rfid2.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 2: ");
    rfid2.PICC_HaltA();
  }
  if (rfid3.PICC_IsNewCardPresent() && rfid3.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 3: ");
    rfid3.PICC_HaltA();}
  if (rfid4.PICC_IsNewCardPresent() && rfid4.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 4: ");
    rfid4.PICC_HaltA();
  }
  if (rfid5.PICC_IsNewCardPresent() && rfid5.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 5: ");
    rfid5.PICC_HaltA();
  }
  if (rfid6.PICC_IsNewCardPresent() && rfid6.PICC_ReadCardSerial()) {
    Serial.print("RFID Reader 6: ");
    rfid6.PICC_HaltA();
  }
}
