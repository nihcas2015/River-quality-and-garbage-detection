/*
 * River Monitor — ESP32-S3-N16R8
 *
 * Hardware:
 *   - ESP32-S3-N16R8 (16 MB Flash, 8 MB PSRAM)
 *   - DS18B20 waterproof temperature sensor  → GPIO 4
 *   - pH sensor module (9 V DC power, analog output) → GPIO 1 (ADC1_CH0)
 *   - Turbidity sensor (TSD-10 + adapter board, analog output) → GPIO 5 (ADC1_CH4)
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
// ── CHANGE THESE THREE VALUES ────────────────────────────
// 1) Your WiFi credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
// 2) Pi4 IP — run 'hostname -I' on your Raspberry Pi 4
//    This MUST match PI4_IP in pi4_edge_node/config.py
const char* MQTT_SERVER   = "192.168.1.101";  // ← Pi4 IP address
const int   MQTT_PORT     = 1883;              // ← matches config.py MQTT_PORT
const char* NODE_ID       = "esp32_node_1";

// Timing
const unsigned long READ_INTERVAL_MS = 10000;  // read sensors every 10 s
const unsigned long MQTT_RETRY_MS    = 5000;

// MQTT topics
const char* TOPIC_SENSOR = "river/sensor_data";
const char* TOPIC_STATUS = "river/status";

// ─── PINS (ESP32-S3) ───────────────────────────────────────
#define DS18B20_PIN      4    // GPIO 4  — OneWire data
#define PH_SENSOR_PIN    1    // GPIO 1  — ADC1_CH0 analog input
#define TURB_SENSOR_PIN  5    // GPIO 5  — ADC1_CH4 analog input
                              // NOTE: GPIO 2 reads 0 on many ESP32-S3 boards
                              //       (onboard pull-down / PSRAM conflict).
                              //       Move the turbidity wire to GPIO 5.

// ─── pH CALIBRATION ─────────────────────────────────────────
// Calibrate with pH 4.0 and pH 7.0 buffer solutions.
// Dip probe in pH 7.0 buffer → note the raw ADC voltage → PH7_VOLTAGE
// Dip probe in pH 4.0 buffer → note the raw ADC voltage → PH4_VOLTAGE
#define PH7_VOLTAGE  1.50   // voltage at pH 7.0  (adjust after calibration)
#define PH4_VOLTAGE  2.03   // voltage at pH 4.0  (adjust after calibration)

// ─── TURBIDITY CALIBRATION ──────────────────────────────────
// Measured calibration points (raw ADC voltage at ESP32 pin):
//   Air (dry)   : 0.600 V  →  sensor not submerged
//   Clean water : 0.915 V  →  0 NTU
// Voltage rises when sensor enters water; as turbidity increases,
// voltage drops below TURB_CLEAN_V → NTU rises.
#define TURB_CLEAN_V       0.915   // ADC voltage in clean water (0 NTU)
#define TURB_AIR_V         0.600   // ADC voltage in air (dry, baseline)
#define TURB_DIVIDER       1.0     // 1.0 = direct connection, no divider
#define TURB_SAMPLES       64      // oversampling count (power of 2)
#define TURB_EMA_ALPHA     0.3     // exponential moving average weight (0–1)
#define TURB_NOISE_FLOOR   3       // raw ADC counts below this = noise
#define TURB_ADC_OFFSET    0.0     // zero-offset correction (V), adjust if needed

// ─── GLOBALS ────────────────────────────────────────────────
OneWire oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

unsigned long lastReadTime = 0;
float turbEMA = -1.0;   // exponential moving average for turbidity (init flag)

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

// ── Helper: sort array for median filter ──
void sortArray(int arr[], int n) {
  for (int i = 0; i < n - 1; i++)
    for (int j = i + 1; j < n; j++)
      if (arr[j] < arr[i]) { int t = arr[i]; arr[i] = arr[j]; arr[j] = t; }
}

// ── Turbidity calibration: ADC voltage → NTU ──
// Based on actual measurements:
//   0.915 V = clean water   →    0 NTU
//   0.600 V = air / dry     →   not submerged (below water baseline)
// When submerged, voltage starts at ~0.915 V (clean water).
// As turbidity increases, voltage drops below TURB_CLEAN_V:
//   0.915 V               →    0 NTU  (clean)
//   0.700 V               →  500 NTU  (moderately turbid)
//   0.400 V               → 2000 NTU  (very turbid)
//   0.000 V               → 3000 NTU  (opaque)
// Uses piecewise linear interpolation from TURB_CLEAN_V downward.
float voltageToNTU(float v) {
  float ntu;

  // If sensor is in air (below air baseline), report 0
  if (v <= TURB_AIR_V) {
    ntu = 0.0;
  } else if (v >= TURB_CLEAN_V) {
    // At or above clean-water voltage → 0 NTU
    ntu = 0.0;
  } else if (v >= 0.70) {
    // 0.915 V → 0 NTU,  0.700 V → 500 NTU  (light turbidity)
    ntu = (TURB_CLEAN_V - v) / (TURB_CLEAN_V - 0.70) * 500.0;
  } else if (v >= 0.40) {
    // 0.700 V → 500 NTU,  0.400 V → 2000 NTU  (moderate→high)
    ntu = 500.0 + (0.70 - v) / (0.70 - 0.40) * 1500.0;
  } else {
    // 0.400 V → 2000 NTU,  0.000 V → 3000 NTU  (very high)
    ntu = 2000.0 + (0.40 - v) / 0.40 * 1000.0;
  }
  // Clamp
  if (ntu < 0.0)    ntu = 0.0;
  if (ntu > 3000.0) ntu = 3000.0;
  return ntu;
}

float readTurbidity() {
  // ─ Step 1: Collect oversampled raw ADC readings ─
  int samples[TURB_SAMPLES];
  long total = 0;
  int minVal = 4095, maxVal = 0;

  for (int i = 0; i < TURB_SAMPLES; i++) {
    samples[i] = analogRead(TURB_SENSOR_PIN);
    total += samples[i];
    if (samples[i] < minVal) minVal = samples[i];
    if (samples[i] > maxVal) maxVal = samples[i];
    delay(5);  // ~320 ms total acquisition
  }
  float rawMean = total / (float)TURB_SAMPLES;

  // ─ Step 2: Median filter (reject impulse noise / outliers) ─
  sortArray(samples, TURB_SAMPLES);
  float rawMedian;
  int mid = TURB_SAMPLES / 2;
  rawMedian = (samples[mid - 1] + samples[mid]) / 2.0;

  // ─ Step 3: Trimmed mean (discard lowest & highest 12.5%) ─
  int trim = TURB_SAMPLES / 8;   // 8 samples on each side
  long trimTotal = 0;
  for (int i = trim; i < TURB_SAMPLES - trim; i++) {
    trimTotal += samples[i];
  }
  float rawTrimmed = trimTotal / (float)(TURB_SAMPLES - 2 * trim);

  // Use the trimmed mean as the best estimate
  float bestRaw = rawTrimmed;

  Serial.printf("  [Turb sample] n=%d  mean=%.1f  median=%.1f  trimmed=%.1f  min=%d  max=%d\n",
                TURB_SAMPLES, rawMean, rawMedian, rawTrimmed, minVal, maxVal);

  // ─ Step 4: Noise floor gating ─
  if (bestRaw < TURB_NOISE_FLOOR) {
    Serial.printf("  [Turb cal]   raw %.1f < noise floor %d → signal too low\n",
                  bestRaw, TURB_NOISE_FLOOR);
    // Still process — don't discard tiny signals
  }

  // ─ Step 5: Convert to voltage ─
  float adcVoltage = (bestRaw * (3.3 / 4095.0)) - TURB_ADC_OFFSET;
  if (adcVoltage < 0.0) adcVoltage = 0.0;

  // ─ Step 6: Undo voltage divider → original sensor voltage ─
  float sensorV = adcVoltage / TURB_DIVIDER;
  if (sensorV > 4.5) sensorV = 4.5;

  Serial.printf("  [Turb cal]   ADC=%.4fV  → Sensor=%.4fV  (divider=%.2f)\n",
                adcVoltage, sensorV, TURB_DIVIDER);

  // ─ Step 7: Multi-segment voltage → NTU calibration ─
  float ntu = voltageToNTU(sensorV);

  Serial.printf("  [Turb cal]   raw NTU=%.2f", ntu);

  // ─ Step 8: Exponential moving average across readings ─
  if (turbEMA < 0.0) {
    turbEMA = ntu;   // first reading — initialize
  } else {
    turbEMA = TURB_EMA_ALPHA * ntu + (1.0 - TURB_EMA_ALPHA) * turbEMA;
  }

  Serial.printf("  → EMA=%.2f (α=%.2f)\n", turbEMA, TURB_EMA_ALPHA);
  Serial.printf("  [Turb result] %.1f NTU\n", turbEMA);

  return turbEMA;
}

void publishSensorData(float temperature, float ph, float turbidity) {
  StaticJsonDocument<256> doc;
  doc["node_id"]     = NODE_ID;
  doc["temperature"] = round(temperature * 100.0) / 100.0;
  doc["ph"]          = round(ph * 100.0) / 100.0;
  doc["turbidity"]   = round(turbidity * 100.0) / 100.0;
  doc["timestamp"]   = millis();

  char buf[256];
  serializeJson(doc, buf);
  mqtt.publish(TOPIC_SENSOR, buf);

  Serial.printf("Published — Temp: %.2f °C  |  pH: %.2f  |  Turb: %.1f NTU\n",
                temperature, ph, turbidity);
}

// ─── SETUP & LOOP ───────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== River Monitor — ESP32-S3-N16R8 ===");

  analogReadResolution(12);       // 12-bit ADC
  analogSetAttenuation(ADC_11db); // full 0-3.3 V range

  // Set attenuation per-pin to ensure it takes effect on ESP32-S3
  analogSetPinAttenuation(PH_SENSOR_PIN,   ADC_11db);
  analogSetPinAttenuation(TURB_SENSOR_PIN, ADC_11db);

  tempSensor.begin();

  // ── ADC pin scanner — find where the signal actually is ──
  delay(500);
  Serial.println("[Boot] Scanning ADC1 pins for signal...");
  const int scanPins[] = {1, 2, 3, 5, 6, 7, 8, 9, 10};
  const int scanCount  = sizeof(scanPins) / sizeof(scanPins[0]);
  for (int p = 0; p < scanCount; p++) {
    analogSetPinAttenuation(scanPins[p], ADC_11db);
    int raw = analogRead(scanPins[p]);
    float v = raw * (3.3 / 4095.0);
    Serial.printf("  GPIO %2d : raw=%4d  (%.3f V)%s\n",
                  scanPins[p], raw, v,
                  (scanPins[p] == TURB_SENSOR_PIN) ? "  ← TURB" :
                  (scanPins[p] == PH_SENSOR_PIN)   ? "  ← pH"   : "");
  }
  int rawTurb = analogRead(TURB_SENSOR_PIN);
  if (rawTurb == 0) {
    Serial.println("WARNING: Turbidity ADC reads 0 on configured pin!");
    Serial.println("  1) Is the TSD-10 sensor board powered (5 V VCC + GND)?");
    Serial.printf("  2) Is the voltage divider output connected to GPIO %d?\n", TURB_SENSOR_PIN);
    Serial.println("  3) Check the pin scan above — if another pin shows voltage,");
    Serial.println("     move #define TURB_SENSOR_PIN to that GPIO number.");
  } else {
    Serial.printf("[Boot] Turbidity pin GPIO %d OK — raw=%d (%.3f V)\n",
                  TURB_SENSOR_PIN, rawTurb, rawTurb * (3.3 / 4095.0));
  }

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
    float turb = readTurbidity();

    if (temp != -999.0) {
      publishSensorData(temp, ph, turb);
    }
  }
}
