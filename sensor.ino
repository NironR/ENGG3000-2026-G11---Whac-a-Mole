#include "BluetoothSerial.h"
#include "esp_system.h"
BluetoothSerial SerialBT;

#define BOX_ID 1  // SENSOR BOX NO.

//Ultrasonic sensor pins
int echoPin1 = 5;   // TODO move off GPIO5: it is a boot strapping pin and Echo idles LOW
int trigPin1 = 18;
int echoPin2 = 19;
int trigPin2 = 21;


void setup() {
  Serial.begin(115200);
  delay(100);

  // On battery this line is the whole diagnosis. Reason 15 (ESP_RST_BROWNOUT)
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
    delay(5);  // yield: without this the BT stack starves and the link drops
    return;
  }
  while (SerialBT.available()) SerialBT.read();
  while (Serial.available()) Serial.read();

  long d1 = readUltraSonicDistanceMm(trigPin1, echoPin1);
  long d2 = readUltraSonicDistanceMm(trigPin2, echoPin2);
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

long readUltraSonicDistanceMm(int trigPin, int echoPin) {
  // Trigger the ultrasonic sensor
  // Set the trigPin low for a short period to ensure a clean signal
  
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 30000); // Wait for the echo, with a timeout of 30ms

  if (duration == 0) {
    // No echo received (timeout)
    return -1; // Indicate an error
  }

  long distanceMm = duration * 0.343 / 2; // Speed of sound is ~343 m/s
  return distanceMm;
}
