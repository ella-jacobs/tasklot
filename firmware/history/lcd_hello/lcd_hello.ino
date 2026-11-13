// lcd_hello — LCD first light. Does the screen turn on and print?
// Elegoo Mega. LCD2004A + I2C backpack: VCC->5V, GND->GND, SDA->20, SCL->21.
// Library: LiquidCrystal_I2C by Frank de Brabander (Library Manager).
// Serial Monitor at 9600.

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// The backpack is either 0x27 or 0x3F and you can't tell by looking,
// so setup() scans the bus and uses whichever one answers.
byte lcdAddress = 0x27;
LiquidCrystal_I2C lcd(0x27, 20, 4);  // 20 characters, 4 lines

byte findLcd() {
  for (byte a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print("Found an I2C device at 0x");
      Serial.println(a, HEX);
      if (a == 0x27 || a == 0x3F) return a;   // that's the backpack
    }
  }
  return 0;   // nothing answered
}

void setup() {
  Serial.begin(9600);
  Wire.begin();

  lcdAddress = findLcd();
  if (lcdAddress == 0) {
    Serial.println("No LCD found. Check 5V, GND, SDA->20, SCL->21.");
    return;
  }

  lcd = LiquidCrystal_I2C(lcdAddress, 20, 4);
  lcd.init();
  lcd.backlight();

  lcd.setCursor(0, 0);
  lcd.print("hello, world");
  lcd.setCursor(0, 1);
  lcd.print("TaskLot is alive");
  lcd.setCursor(0, 2);
  lcd.print("20 chars x 4 lines");
  lcd.setCursor(0, 3);
  lcd.print("01234567890123456789");   // ruler: shows where line 20 lands

  Serial.println("LCD ready.");
}

void loop() {
}
