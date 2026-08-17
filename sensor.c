#include "BluetoothSerial.h";

//Ultrasonic sensor pins
int echoPin1 = 5;
int trigPin1 = 18;
int echoPin2 = 19;
int trigPin2 = 21;

//Timing
const unsigned long SLOT_DURATION_MS = 40; // each box's slot within the cycle
const unsigned long CYCLE_MS = SLOT_DURATION_MS * 3; // total cycle duration for all boxes

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
  //Wait until its this box's turn in the cycle
  unsigned long cyclePosition = millis() % CYCLE_MS;
  unsigned long slotStartTime = (BOX_ID - 1) * SLOT_DURATION_MS;
  unsigned long slotEndTime = slotStartTime + SLOT_DURATION_MS;

  bool isMySlot = (cyclePosition >= slotStartTime) && (cyclePosition < slotEndTime);

  if (isMySlot) {
    long d1 = readUltraSonicDistanceMm(trigPin1, echoPin1);
    long d2 = readUltraSonicDistanceMm(trigPin2, echoPin2);

    long combined = combineReadings(d1, d2);

    if (combined >= 0) {
      String message = String(BOX_ID) + " DIST " + String(combined) + "\n";
      SerialBT.print(message);
      Serial.print("Sent: " + message);
    } else {
      Serial.println(String(BOX_ID) + " DIST ERROR");
    }
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
