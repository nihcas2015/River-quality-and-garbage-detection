# Federated River Monitoring System

A real-time river water quality monitoring system using **ESP32-S3**, **Raspberry Pi 4**, and **Raspberry Pi 5** with federated learning for trash detection.

---

## System Architecture

```
┌─────────────────┐      ┌──────────────────────────────┐
│  ESP32-S3-N16R8 │      │       Raspberry Pi 5          │
│  (River sensor) │      │                                │
│                 │      │   Flask server (:5000)          │
│  • DS18B20 temp │      │   ├─ REST API                  │
│  • pH sensor    │      │   ├─ WebSocket (live push)      │
│                 │      │   ├─ Federated aggregation      │
└────────┬────────┘      │   └─ Serves React dashboard     │
         │ WiFi+MQTT     │                                │
         ▼               │   Open http://<Pi5_IP>:5000     │
┌─────────────────┐      │   from any device on the LAN    │
│  Raspberry Pi 4 │─────►│                                │
│   Edge Node     │ HTTP └────────────────────────────────┘
│                 │
│  • MQTT broker  │
│  • YOLOv8 trash │
│  • Pi Camera V2 │
└─────────────────┘
```

**Data flow:** ESP32 reads sensors → publishes via MQTT → Pi4 subscribes, runs YOLOv8 on camera frames → sends aggregated data to Pi5 → Pi5 serves the dashboard and pushes live updates via WebSocket.

> **The dashboard runs entirely on Pi5.** Open `http://<Pi5_IP>:5000` from any phone, tablet, or laptop on the same network — no extra software needed.

---

## Hardware Required

| Component | Model | Quantity |
|-----------|-------|----------|
| Microcontroller | **ESP32-S3-N16R8** (16 MB Flash, 8 MB PSRAM) | 1 |
| Temperature sensor | **DS18B20** waterproof probe | 1 |
| pH sensor module | Analog pH sensor with **9V DC** power (2-pin power + 2-pin output) | 1 |
| Edge computer | **Raspberry Pi 4** (4 GB+ RAM) | 1 |
| Camera | **Raspberry Pi Camera Module V2** | 1 |
| Central server | **Raspberry Pi 5** (4 GB+ RAM) | 1 |
| Resistor | 4.7 kΩ (pull-up for DS18B20) | 1 |
| Power supply | 9V DC adapter (for pH sensor) | 1 |
| Power supply | 5V USB-C (for ESP32-S3, Pi4, Pi5) | 3 |
| Breadboard + jumper wires | — | 1 set |
| MicroSD cards | 32 GB+ (for Pi4 and Pi5) | 2 |

---

## Wire Connections

### 1. ESP32-S3-N16R8 + DS18B20 Temperature Sensor

```
DS18B20 (waterproof probe, 3 wires):

  RED wire ──────── 3.3V  (ESP32-S3 pin: 3V3)
  BLACK wire ────── GND   (ESP32-S3 pin: GND)
  YELLOW wire ───── GPIO 4 (ESP32-S3 data pin)

  ⚠ 4.7 kΩ resistor (pull-up):
    • One end → placed between the 3V3 pin and the RED wire
    • Other end → placed between GPIO 4 and the YELLOW wire
    (This bridges the power rail to the data line)

Wiring diagram:

  ESP32-S3                DS18B20
  ────────                ───────

  3V3 ─────┬──────────── RED
           │
      [4.7kΩ resistor]
           │
  GPIO 4 ──┴──────────── YELLOW (data)

  GND ────────────────── BLACK

  On a breadboard:
    Row A: 3V3 wire + RED wire + one leg of resistor
    Row B: GPIO 4 wire + YELLOW wire + other leg of resistor
    Row C: GND wire + BLACK wire
```

### 2. ESP32-S3-N16R8 + pH Sensor Module (9V DC)

The pH sensor module has **two connectors**:
- **Power input** (2-pin): Connect to external 9V DC adapter
- **Signal output** (2-pin): Analog voltage output (0–3.3V proportional to pH)

```
pH Sensor Module
┌─────────────────────────┐
│                         │
│  POWER INPUT (2-pin):   │       9V DC Adapter
│    (+) ─────────────────┼────── (+) positive
│    (−) ─────────────────┼────── (−) negative / GND
│                         │
│  SIGNAL OUTPUT (2-pin): │       ESP32-S3
│    Signal (Vo) ─────────┼────── GPIO 1  (ADC1_CH0)
│    GND ─────────────────┼────── GND
│                         │
│  BNC connector ← pH probe (glass electrode)
└─────────────────────────┘

Wiring diagram:

  9V DC Adapter           pH Module            ESP32-S3
  ──────────────          ─────────            ────────
  (+) ──────────────────► Power (+)
  (−) ──────────────┬───► Power (−)
                    │
                    │    Signal (Vo) ────────► GPIO 1
                    └───► Signal GND ────────► GND
```

> **Important:** The pH module needs its own **9V DC power supply**. Do NOT power it from the ESP32's 3.3V or 5V — it will not work correctly.

### 3. Raspberry Pi 4 + Pi Camera V2

```
  1. Locate the CSI camera port on Pi4 (between HDMI and audio jack)
  2. Gently pull up the plastic clip on the CSI connector
  3. Insert the Camera V2 ribbon cable:
     - Blue side facing the Ethernet/USB ports
     - Silver contacts facing the HDMI port
  4. Press the plastic clip back down to lock the cable
```

### 4. Full Wiring Summary

```
┌──────────────────────────────────────────────────────────┐
│                    ESP32-S3-N16R8                         │
│                                                          │
│  3V3  ──── DS18B20 RED + resistor leg 1                   │
│  GND  ──── DS18B20 BLACK + pH module signal GND          │
│  GPIO 4 ── DS18B20 YELLOW (data) + resistor leg 2       │
│          (4.7kΩ resistor bridges 3V3 ↔ GPIO 4)           │
│  GPIO 1 ── pH module signal output (Vo)                  │
│                                                          │
│  USB-C ─── 5V power supply                               │
│  WiFi ──── connects to same network as Pi4               │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  9V DC Adapter ──── pH module power input (2-pin)        │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    Raspberry Pi 4                         │
│                                                          │
│  CSI port ── Pi Camera V2 (ribbon cable)                 │
│  USB-C ───── 5V power supply                             │
│  WiFi/Eth ── same network as ESP32 and Pi5               │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5                         │
│                                                          │
│  USB-C ───── 5V power supply                             │
│  WiFi/Eth ── same network as Pi4                         │
└──────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Implementation

### Step 1 — Set Up the Raspberry Pi5 (Central Server + Dashboard)

1. **Flash Raspberry Pi OS** (64-bit) to a MicroSD card using Raspberry Pi Imager.
2. Boot Pi5, connect to WiFi/Ethernet, note its IP address:
   ```bash
   hostname -I
   ```
3. **Install Node.js** (needed once to build the dashboard):
   ```bash
   sudo apt update
   sudo apt install -y nodejs npm
   ```
4. **Build the React dashboard:**
   ```bash
   cd dashboard/frontend
   npm install
   npm run build
   cd ../..            # back to project root
   ```
   This creates a `dashboard/frontend/build/` folder with static files.
5. **Create a Python virtual environment and install dependencies:**
   ```bash
   cd pi5_central_node
   python3 -m venv --system-site-packages venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   > On Raspberry Pi OS Bookworm+, `pip install` outside a venv is blocked. Always activate the venv first.
6. **Start the server:**
   ```bash
   source venv/bin/activate      # if not already activated
   python server.py
   ```
   The server runs on **port 5000** and hosts both the API and the dashboard.
7. Open **http://`<Pi5_IP>`:5000** from any device on the network to see the dashboard.

### Step 2 — Set Up the Raspberry Pi4 (Edge Node)

1. **Flash Raspberry Pi OS** (64-bit) to a MicroSD card.
2. Boot Pi4, connect to the **same network** as Pi5.
3. **Enable the camera:**
   ```bash
   sudo raspi-config
   # Interface Options → Camera → Enable → Reboot
   ```
4. **Install Mosquitto MQTT broker:**
   ```bash
   sudo apt update
   sudo apt install -y mosquitto mosquitto-clients
   sudo systemctl enable mosquitto
   ```
5. **Create a Python virtual environment and install dependencies:**
   ```bash
   cd pi4_edge_node
   python3 -m venv --system-site-packages venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   > `--system-site-packages` is **required** so the venv can access the system-installed `picamera2` (which cannot be pip-installed without conflicts).
6. **Edit config.py** — set the Pi5 IP address:
   ```python
   SERVER_URL = "http://<PI5_IP>:5000"
   ```
7. **Place your YOLOv8 model** (`best.pt`) in the `pi4_edge_node/` folder.
8. **Start the edge node:**
   ```bash
   source venv/bin/activate      # if not already activated
   python main_edge.py
   ```

### Step 3 — Set Up the ESP32-S3-N16R8

1. **Install Arduino IDE** (2.x recommended).
2. **Add ESP32 board support:**
   - File → Preferences → Additional Board Manager URLs:
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Tools → Board → Board Manager → search "esp32" → install **esp32 by Espressif Systems**.
3. **Install libraries** (Sketch → Include Library → Manage Libraries):
   - `OneWire`
   - `DallasTemperature`
   - `PubSubClient`
   - `ArduinoJson`
4. **Open** `esp32/river_monitor/river_monitor.ino`.
5. **Edit the configuration** at the top of the file:
   ```cpp
   const char* WIFI_SSID     = "YourWiFiName";
   const char* WIFI_PASSWORD = "YourWiFiPassword";
   const char* MQTT_SERVER   = "<PI4_IP_ADDRESS>";
   ```
6. **Select the board:**
   - Tools → Board → **ESP32S3 Dev Module**
   - Tools → USB CDC On Boot → **Enabled**
   - Tools → Flash Size → **16MB**
   - Tools → PSRAM → **OPI PSRAM**
   - Tools → Upload Speed → **921600**
7. **Connect** the ESP32-S3 via USB-C and **Upload**.
8. Open **Serial Monitor** (115200 baud) to verify:
   ```
   === River Monitor — ESP32-S3-N16R8 ===
   Connecting to WiFi... connected — IP: 192.168.x.x
   Connecting to MQTT... connected
   Published — Temp: 24.50 °C  |  pH: 7.12
   ```

### Step 4 — pH Sensor Calibration

1. Power ON the pH module with the 9V adapter.
2. Open Serial Monitor on the ESP32.
3. **pH 7.0 buffer:** Dip the probe → note the voltage printed. Update `PH7_VOLTAGE` in the `.ino` file.
4. **pH 4.0 buffer:** Dip the probe → note the voltage. Update `PH4_VOLTAGE`.
5. Re-upload the firmware.

### Step 5 — Access the Dashboard

The dashboard is hosted on the Pi5 — no extra setup needed.

1. Open a browser on **any device** (phone, tablet, laptop) connected to the same network.
2. Go to:
   ```
   http://<PI5_IP>:5000
   ```
3. You should see the live River Monitoring Dashboard with real-time sensor data.

> **Tip:** If you need to rebuild the dashboard after editing React code, run `cd dashboard/frontend && npm run build` on the Pi5 and restart `server.py`.

---

## Project Structure

```
├── esp32/
│   └── river_monitor/
│       └── river_monitor.ino      # ESP32-S3 firmware (sensors + MQTT)
│
├── pi4_edge_node/
│   ├── config.py                  # Configuration (IPs, thresholds, timing)
│   ├── main_edge.py               # Main entry point (3 threads)
│   ├── sensor_reader.py           # MQTT subscriber for ESP32 data
│   ├── trash_detector.py          # YOLOv8 inference on camera frames
│   ├── federated_client.py        # HTTP client for Pi5 communication
│   ├── requirements.txt           # Python dependencies
│   ├── best.pt                    # YOLOv8 trained model (you provide)
│   └── best.onnx                  # ONNX version (optional)
│
├── pi5_central_node/
│   ├── server.py                  # Flask API + WebSocket + serves dashboard
│   ├── federated_server.py        # FedAvg aggregation logic
│   └── requirements.txt           # Python dependencies
│
└── dashboard/
    └── frontend/
        ├── package.json           # React dependencies
        ├── public/index.html      # HTML entry point
        └── src/
            ├── App.js             # Root component (routing, WebSocket)
            ├── index.js           # React DOM render
            ├── api/client.js      # Axios HTTP client
            ├── components/        # Reusable UI components
            ├── pages/             # Dashboard, Nodes, Trash, Alerts, Settings
            └── styles/            # CSS for each component/page
```

---

## Network Setup

All devices must be on the **same WiFi/LAN network**.

| Device | Role | Port |
|--------|------|------|
| ESP32-S3 | Sensor node | — (MQTT client) |
| Raspberry Pi 4 | Edge node + MQTT broker | 1883 (MQTT) |
| Raspberry Pi 5 | Central server + Dashboard | 5000 (API + Web UI) |

**IP addresses to configure (only two places):**
- In `river_monitor.ino` → set `MQTT_SERVER` to your **Pi4 IP**
- In `pi4_edge_node/config.py` → set `SERVER_URL` to your **Pi5 IP**

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ESP32 can't connect to WiFi | Check SSID/password, ensure 2.4 GHz network |
| MQTT connection failed | Verify Mosquitto running on Pi4: `sudo systemctl status mosquitto` |
| No sensor data on dashboard | Check ESP32 Serial Monitor, verify Pi4 `main_edge.py` is running |
| Camera not detected | Run `sudo raspi-config` → enable camera, reboot Pi4 |
| Dashboard shows "Disconnected" | Ensure Pi5 `server.py` is running, try `http://<Pi5_IP>:5000/api/health` |
| Dashboard page is blank | Run `npm run build` in `dashboard/frontend/` on Pi5, then restart `server.py` |
| pH readings are wrong | Recalibrate with pH 4.0 and pH 7.0 buffer solutions |
