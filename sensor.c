// SENSOR PINS
// PIN 1 - trig 25, echo 34
int echoPin1 = 34;
int trigPin1 = 25;

float sensor1Distance;

const float DETECT_CM = 50.0;
const float MAX_RANGE_CM = 200.0;

void setup() {
  Serial.begin(115200);
  delay(1000); // give USB serial time to stabilize after reset

  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);

  digitalWrite(trigPin1, LOW); // ensure known state at boot

  Serial.println("BOOT OK - Sensor test starting");
}

float getDistance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 20000); // 20ms timeout

  if (duration == 0) {
    return -1.0; // no echo received (timeout)
  }

  float distance = (duration * 0.0343f) / 2.0f;

  if (distance > MAX_RANGE_CM) {
    return -1.0; // out of realistic range, treat as no detection
  }

  return distance;
}

void loop() {
  sensor1Distance = getDistance(trigPin1, echoPin1);

  if (sensor1Distance < 0) {
    Serial.println("No echo");
  } else {
    Serial.print("Distance: ");
    Serial.print(sensor1Distance);
    Serial.println(" cm");
  }

  delay(200); // slower loop for readable monitor output
}
