# Configuration for Raspberry Pi 4 Edge Node
# ───────────────────────────────────────────
# INSTRUCTIONS:
#   1. On your Pi5, run: hostname -I
#   2. Replace PI5_IP below with that address (e.g. "192.168.1.50")
#   3. On your Pi4, run: hostname -I  → use that as PI4_IP in ESP32 code
# ───────────────────────────────────────────

# ── Network addresses ─────────────────────
PI5_IP   = "192.168.1.100"          # ← Pi5 IP (run 'hostname -I' on Pi5)
PI5_PORT = 5000                      # ← Pi5 server port (must match server.py)
SERVER_URL = f"http://{PI5_IP}:{PI5_PORT}"

PI4_IP   = "192.168.1.101"          # ← This Pi4's IP (for ESP32 MQTT target)
NODE_ID  = "pi4_edge_01"

# ── MQTT (Mosquitto runs on this Pi4) ─────
MQTT_BROKER = "localhost"            # ESP32 connects to this Pi4's IP
MQTT_PORT   = 1883
MQTT_TOPIC_DATA   = "river/sensor_data"
MQTT_TOPIC_STATUS = "river/status"

# ── Pi Camera V2 (libcamera-still) ────────
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480

# ── YOLOv8 Model ─────────────────────────
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
SENSOR_POLL         = 5
DETECTION_INTERVAL  = 2
SEND_INTERVAL       = 10
HEARTBEAT_INTERVAL  = 15
FEDERATION_INTERVAL = 120    # seconds between federated learning rounds

# Anomaly thresholds (absolute bounds)
TEMP_MIN = 4.0
TEMP_MAX = 35.0
PH_MIN = 6.0
PH_MAX = 9.0
TURBIDITY_MIN = 0.0
TURBIDITY_MAX = 500.0       # NTU — above 500 is extreme (flood/mudslide)

# Time-series anomaly detection
ANOMALY_WINDOW = 30           # sliding window size (number of readings)
ANOMALY_Z_THRESHOLD = 2.5     # Z-score to flag a statistical outlier
ANOMALY_TEMP_SPIKE = 5.0      # °C change in one reading = spike
ANOMALY_PH_SPIKE = 1.0        # pH change in one reading  = spike
ANOMALY_TURB_SPIKE = 100.0    # NTU change in one reading  = spike
ANOMALY_EWMA_ALPHA = 0.3      # EWMA smoothing factor (0–1, higher = more reactive)
