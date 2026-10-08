#include "BluetoothSerial.h"
#include "esp_system.h"
BluetoothSerial SerialBT;

#define BOX_ID 1  // SENSOR BOX NO.

//Ultrasonic sensor pins
int echoPin1 = 5;   // TODO move off GPIO5: it is a boot strapping pin and Echo idles LOW
int trigPin1 = 18;
int echoPin2 = 19;
int trigPin2 = 21;

const unsigned long ECHO_TIMEOUT_US = 15000;
const unsigned long ECHO_START_US = 2000;


void setup() {
  Serial.begin(115200);
  delay(100);

  // On battery this line is the whole diagnosis.
  // means the pack sagged below what the chip needs - almost always when the
  // Bluetooth radio switched on and took its first big gulp of current. No
  // amount of firmware fixes that; it needs a steadier supply.
  esp_reset_reason_t reason = esp_reset_reason();
  Serial.print("Reset reason: ");
  Serial.print(reason);
  Serial.println(reason == ESP_RST_BROWNOUT ? "  <-- BROWNOUT: supply is sagging" : "");

  String btName = "ENGG3000_";
  btName += BOX_ID;
  if (SerialBT.begin(btName)) {
    Serial.println("Bluetooth started: " + btName);
  } else {
    Serial.println("Bluetooth FAILED to start - not a power fault, the stack itself refused");
  }

  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);
  pinMode(trigPin2, OUTPUT);
  pinMode(echoPin2, INPUT);
}


void loop() {
  // The PC is the conductor: it asks one box at a time, so only one sensor is
  // ever listening and the boxes can't mistake each other's clicks for echoes.
  // Self-timing this with millis() cannot work - each box's clock starts when
  // that box is switched on, so three boxes never agree on when a slot begins.
  // Any byte on either link means "your turn" (USB included, so the Arduino
  // Serial Monitor can drive a bench test without the PC game running).
  if (!SerialBT.available() && !Serial.available()) {
    delay(1);  // yield: without this the BT stack starves and the link drops
    return;
  }
  while (SerialBT.available()) SerialBT.read();
  while (Serial.available()) Serial.read();

  long d1, d2;
  readBothDistancesMm(d1, d2);
  long combined = combineReadings(d1, d2);  // -1 = looked, saw nothing

  SerialBT.println(String(BOX_ID) + " DIST " + String(combined));
  Serial.println(String(BOX_ID) + " DIST " + String(combined) + "  (d1=" + String(d1) + " d2=" + String(d2) + ")");
}

long combineReadings(long d1, long d2) {
  bool validD1 = (d1 >= 0);
  bool validD2 = (d2 >= 0);

  if (validD1 && validD2) {
    return (d1 + d2) / 2; // Average the two readings
  } else if (validD1) {
    return d1; // Only d1 is valid
  } else if (validD2) {
    return d2; // Only d2 is valid
  } else {
    return -1; // Both readings are invalid
  }
}

void readBothDistancesMm(long &d1, long &d2) {
  digitalWrite(trigPin1, LOW);
  digitalWrite(trigPin2, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin1, HIGH);
  digitalWrite(trigPin2, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin1, LOW);
  digitalWrite(trigPin2, LOW);

  unsigned long started = micros();
  unsigned long rose1 = 0, rose2 = 0;
  bool risen1 = false, risen2 = false;
  d1 = -1;
  d2 = -1;

  while (micros() - started < ECHO_START_US + ECHO_TIMEOUT_US) {
    unsigned long now = micros();
    bool high1 = digitalRead(echoPin1);
    bool high2 = digitalRead(echoPin2);

    if (!risen1 && high1) { risen1 = true; rose1 = now; }
    else if (risen1 && d1 < 0 && !high1) d1 = echoToMm(now - rose1);

    if (!risen2 && high2) { risen2 = true; rose2 = now; }
    else if (risen2 && d2 < 0 && !high2) d2 = echoToMm(now - rose2);

    if (d1 >= 0 && d2 >= 0) break;
  }
}

long echoToMm(unsigned long roundTripUs) {
  if (roundTripUs > ECHO_TIMEOUT_US) return -1;
  return roundTripUs * 0.343 / 2;
}
