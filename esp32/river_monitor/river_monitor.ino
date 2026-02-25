/*
 * River Monitor — ESP32-S3-N16R8
 *
 * Hardware:
 *   - ESP32-S3-N16R8 (16 MB Flash, 8 MB PSRAM)
 *   - DS18B20 waterproof temperature sensor  → GPIO 4
 *   - pH sensor module (9 V DC power, analog output) → GPIO 1 (ADC1_CH0)
 *   - WiFi → connects to local network, publishes via MQTT
 *
 * Libraries (install via Arduino Library Manager):
 *   - OneWire
 *   - DallasTemperature
 *   - PubSubClient (MQTT)
 *   - ArduinoJson
 *
 * Board in Arduino IDE:
 *   Board Manager → esp32 by Espressif → "ESP32S3 Dev Module"
 *   USB CDC On Boot: Enabled   |   Flash Size: 16 MB
 *   PSRAM: OPI PSRAM            |   Upload Speed: 921600
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>

// ─── USER CONFIG ────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_SERVER   = "RASPBERRY_PI4_IP";   // Pi 4 IP address
const int   MQTT_PORT     = 1883;
const char* NODE_ID       = "esp32_node_1";

// Timing
const unsigned long READ_INTERVAL_MS = 10000;  // read sensors every 10 s
const unsigned long MQTT_RETRY_MS    = 5000;

// MQTT topics
const char* TOPIC_SENSOR = "river/sensor_data";
const char* TOPIC_STATUS = "river/status";

// ─── PINS (ESP32-S3) ───────────────────────────────────────
#define DS18B20_PIN   4    // GPIO 4  — OneWire data
#define PH_SENSOR_PIN 1    // GPIO 1  — ADC1_CH0 analog input

// ─── pH CALIBRATION ─────────────────────────────────────────
// Calibrate with pH 4.0 and pH 7.0 buffer solutions.
// Dip probe in pH 7.0 buffer → note the raw ADC voltage → PH7_VOLTAGE
// Dip probe in pH 4.0 buffer → note the raw ADC voltage → PH4_VOLTAGE
#define PH7_VOLTAGE  1.50   // voltage at pH 7.0  (adjust after calibration)
#define PH4_VOLTAGE  2.03   // voltage at pH 4.0  (adjust after calibration)

// ─── GLOBALS ────────────────────────────────────────────────
OneWire oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastReadTime = 0;

// ─── FUNCTIONS ──────────────────────────────────────────────

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi connected — IP: %s\n", WiFi.localIP().toString().c_str());
}

void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT...");
    if (mqtt.connect(NODE_ID)) {
      Serial.println(" connected");
      StaticJsonDocument<128> doc;
      doc["node_id"] = NODE_ID;
      doc["status"]  = "online";
      char buf[128];
      serializeJson(doc, buf);
      mqtt.publish(TOPIC_STATUS, buf);
    } else {
      Serial.printf(" failed (rc=%d), retrying...\n", mqtt.state());
      delay(MQTT_RETRY_MS);
    }
  }
}

float readTemperature() {
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  if (t == DEVICE_DISCONNECTED_C) {
    Serial.println("DS18B20 not detected");
    return -999.0;
  }
  return t;
}

float readPH() {
  // Average 20 ADC samples for stability
  long total = 0;
  for (int i = 0; i < 20; i++) {
    total += analogRead(PH_SENSOR_PIN);
    delay(10);
  }
  float avgRaw = total / 20.0;

  // ESP32-S3 ADC: 12-bit (0-4095), 0-3.3 V
  float voltage = avgRaw * (3.3 / 4095.0);

  // Linear conversion: pH = 7.0 + (PH7_VOLTAGE - voltage) / slope
  float slope = (PH7_VOLTAGE - PH4_VOLTAGE) / (7.0 - 4.0);
  float ph = 7.0 + (PH7_VOLTAGE - voltage) / slope;

  // Clamp to valid range
  if (ph < 0.0) ph = 0.0;
  if (ph > 14.0) ph = 14.0;
  return ph;
}

void publishSensorData(float temperature, float ph) {
  StaticJsonDocument<256> doc;
  doc["node_id"]     = NODE_ID;
  doc["temperature"] = round(temperature * 100.0) / 100.0;
  doc["ph"]          = round(ph * 100.0) / 100.0;
  doc["timestamp"]   = millis();

  char buf[256];
  serializeJson(doc, buf);
  mqtt.publish(TOPIC_SENSOR, buf);

  Serial.printf("Published — Temp: %.2f °C  |  pH: %.2f\n", temperature, ph);
}

// ─── SETUP & LOOP ───────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== River Monitor — ESP32-S3-N16R8 ===");

  analogReadResolution(12);       // 12-bit ADC
  analogSetAttenuation(ADC_11db); // full 0-3.3 V range

  tempSensor.begin();
  connectWiFi();

  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  if (millis() - lastReadTime >= READ_INTERVAL_MS) {
    lastReadTime = millis();

    float temp = readTemperature();
    float ph   = readPH();

    if (temp != -999.0) {
      publishSensorData(temp, ph);
    }
  }
}
