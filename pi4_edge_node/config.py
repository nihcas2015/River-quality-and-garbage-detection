# Configuration for Raspberry Pi 4 Edge Node
# ───────────────────────────────────────────
# QUICK START:
#   1. On your Pi5, run: hostname -I
#   2. Replace PI5_IP below with that IP (e.g., "192.168.1.50")
#   3. On your Pi4, run: hostname -I  → update PI4_IP
#   4. On your ESP32, update MQTT_SERVER to PI4's IP
# CRITICAL CHECKS:
#   - Pi5 must have server.py running: python server.py
#   - Pi4 must have Mosquitto running: sudo systemctl start mosquitto
#   - ESP32 must connect to WiFi and have correct MQTT_SERVER IP
# ───────────────────────────────────────────

# ── Network addresses ─────────────────────
PI5_IP   = "192.168.1.100"          # ← Pi5 IP (run 'hostname -I' on Pi5)
PI5_PORT = 5000                      # ← Pi5 server port (must match server.py)
SERVER_URL = f"http://{PI5_IP}:{PI5_PORT}"

PI4_IP   = "192.168.1.101"          # ← This Pi4's IP (for ESP32 MQTT target)
NODE_ID  = "pi4_edge_01"

# ── MQTT (Mosquitto runs on this Pi4) ─────
# CRITICAL: Ensure Mosquitto is installed and running!
#   Install: sudo apt update && sudo apt install -y mosquitto mosquitto-clients
#   Start: sudo systemctl start mosquitto
#   Check: sudo systemctl status mosquitto
#   Test: mosquitto_sub -h localhost -t "river/sensor_data"
MQTT_BROKER = "localhost"            # ESP32 connects to this Pi4's IP (NOT localhost)
MQTT_PORT   = 1883                   # Default MQTT port
MQTT_TOPIC_DATA   = "river/sensor_data"
MQTT_TOPIC_STATUS = "river/status"

# ── Pi Camera V2 (libcamera-still) ────────
# CRITICAL: libcamera-still must be installed!
#   Install: sudo apt install -y libcamera-tools
#   Test: libcamera-still -n -t 1 -o test.jpg
#   List cameras: libcamera-hello --list-cameras
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480

# ── YOLOv8 Model ─────────────────────────
# CRITICAL: One of these files must exist in current directory!
#   Option 1 (ONNX, fastest on Pi4): best.onnx
#   Option 2 (PyTorch): best.pt
#   Option 3 (Both): system will try ONNX first → PT fallback
MODEL_PATH = "best.pt"               # trained on river-trash dataset
MODEL_ONNX = "best.onnx"             # ONNX export for faster Pi4 inference
CONFIDENCE = 0.3                      # match notebook conf=0.3

# ── YOLO class names (from river-trash dataset.yaml) ──
YOLO_CLASSES = [
    "Plastic",
    "Paper",
    "Metal",
    "Glass",
    "Organic",
    "Textile",
]
# If your dataset has different classes, update this list to match
# the 'names' field in your data.yaml

# ── Timing (seconds) ─────────────────────
SENSOR_POLL         = 5              # How often to check sensor readings
DETECTION_INTERVAL  = 2              # How often to run YOLOv8 inference
SEND_INTERVAL       = 10             # How often to send data to Pi5
HEARTBEAT_INTERVAL  = 15             # How often to send heartbeat to Pi5
FEDERATION_INTERVAL = 120            # seconds between federated learning rounds

# Anomaly thresholds (absolute bounds)
TEMP_MIN = 4.0
TEMP_MAX = 35.0
PH_MIN = 6.0
PH_MAX = 9.0
TURBIDITY_MIN = 0.0
TURBIDITY_MAX = 500.0               # NTU — above 500 is extreme (flood/mudslide)

# Time-series anomaly detection
ANOMALY_WINDOW = 30                  # sliding window size (number of readings)
ANOMALY_Z_THRESHOLD = 2.5            # Z-score to flag a statistical outlier
ANOMALY_TEMP_SPIKE = 5.0             # °C change in one reading = spike
ANOMALY_PH_SPIKE = 1.0               # pH change in one reading  = spike
ANOMALY_TURB_SPIKE = 100.0           # NTU change in one reading  = spike
ANOMALY_EWMA_ALPHA = 0.3             # EWMA smoothing factor (0–1, higher = more reactive)
