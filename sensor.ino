#include "BluetoothSerial.h"
BluetoothSerial SerialBT;

#define BOX_ID 1  // SENSOR BOX NO.

//Ultrasonic sensor pins
int echoPin1 = 5;
int trigPin1 = 18;
int echoPin2 = 19;
int trigPin2 = 21;

//Timing
const unsigned long SLOT_DURATION_MS = 40; // each box's slot within the cycle
const unsigned long CYCLE_MS = SLOT_DURATION_MS * 3; // total cycle duration for all boxes

// Warning Distance
const long WARNING_DISTANCE_MM = 500; // 50cm


void setup() {
  Serial.begin(115200);

  String btName = "ENGG3000_";
  btName += BOX_ID;
  SerialBT.begin(btName);
  Serial.println("Bluetooth started: " + btName);

  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);
  pinMode(trigPin2, OUTPUT);
  pinMode(echoPin2, INPUT);
}


void loop() {
  // One measurement + one send per cycle. Sending as fast as the loop can spin
  // floods the Bluetooth TX buffer and never yields to the BT/idle tasks, which
  // is what drops the link (and trips the task watchdog) seconds after connecting.
  static unsigned long lastCycleSent = 0;

  unsigned long now = millis();
  unsigned long cycle = now / CYCLE_MS;
  unsigned long cyclePosition = now % CYCLE_MS;
  unsigned long slotStartTime = (BOX_ID - 1) * SLOT_DURATION_MS;

  if (cyclePosition < slotStartTime || cyclePosition >= slotStartTime + SLOT_DURATION_MS || cycle == lastCycleSent) {
    delay(1);  // yield: without this the BT stack starves and the link drops
    return;
  }

  lastCycleSent = cycle;

  long d1 = readUltraSonicDistanceMm(trigPin1, echoPin1);
  long d2 = readUltraSonicDistanceMm(trigPin2, echoPin2);

  bool warning =
    (d1 >= 0 && d1 <= WARNING_DISTANCE_MM) || (d2 >= 0 && d2 <= WARNING_DISTANCE_MM);

  if (warning) {
    SerialBT.println(String(BOX_ID) + " WARNING");
    Serial.println(String(BOX_ID) + " WARNING");
  }

  long combined = combineReadings(d1, d2);

  if (combined >= 0) {
    String message = String(BOX_ID) + " DIST " + String(combined);
    SerialBT.println(message);
    Serial.println("Sent: " + message + "  (d1=" + String(d1) + " d2=" + String(d2) + ")");
  } else {
    Serial.println(String(BOX_ID) + " DIST ERROR d1=" + String(d1) + " d2=" + String(d2));
  }
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
