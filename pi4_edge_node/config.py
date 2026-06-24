# Configuration for Raspberry Pi 4 Edge Node
# ───────────────────────────────────────────
# QUICK START:
#   1. Sign up free at https://www.hivemq.com/mqtt-cloud-broker/
#   2. Create a free cluster — get host, username, password
#   3. Replace HIVEMQ_HOST, HIVEMQ_USERNAME, HIVEMQ_PASSWORD below
#   4. Update PI5_IP if Pi5 is running the aggregation server
# ───────────────────────────────────────────

# ── Pi5 Central Server ────────────────────
PI5_IP   = "192.168.1.100"          # ← Pi5 IP (run 'hostname -I' on Pi5)
PI5_PORT = 5000
SERVER_URL = f"http://{PI5_IP}:{PI5_PORT}"

PI4_IP   = "192.168.1.101"
NODE_ID  = "pi4_edge_01"

# ── HiveMQ Cloud MQTT ─────────────────────
# Free tier: https://www.hivemq.com/mqtt-cloud-broker/
# Supports 100 simultaneous connections, 10GB/month — enough for all zones
# Zones can be ANY distance apart — each just needs internet access
MQTT_BROKER   = "YOUR_CLUSTER.s1.eu.hivemq.cloud"  # ← from HiveMQ dashboard
MQTT_PORT     = 8883                                 # TLS port (HiveMQ cloud uses 8883)
MQTT_USERNAME = "YOUR_HIVEMQ_USERNAME"               # ← from HiveMQ dashboard
MQTT_PASSWORD = "YOUR_HIVEMQ_PASSWORD"               # ← from HiveMQ dashboard
MQTT_USE_TLS  = True                                 # HiveMQ cloud requires TLS

MQTT_TOPIC_DATA    = "river/sensor_data"
MQTT_TOPIC_STATUS  = "river/status"
MQTT_TOPIC_UNKNOWN = "river/unknown_objects"         # new: unknown object alerts

# ── Pi Camera V2 ──────────────────────────
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480

# ── YOLOv8 Model ─────────────────────────
MODEL_PATH = "best.pt"
MODEL_ONNX = "best.onnx"
CONFIDENCE = 0.3

# ── YOLO class names ──────────────────────
YOLO_CLASSES = [
    "Plastic",
    "Paper",
    "Metal",
    "Glass",
    "Organic",
    "Textile",
]

# ── Unknown Object Discovery ──────────────
# Object is flagged unknown if max confidence is below this threshold
UNKNOWN_CONFIDENCE_THRESHOLD = 0.45
# How many unknown sightings before creating a new label
UNKNOWN_CLUSTER_THRESHOLD    = 10
# Folder to save unknown object images locally
UNKNOWN_IMAGES_DIR           = "unknown_objects"

# ── Timing (seconds) ─────────────────────
SENSOR_POLL         = 5
DETECTION_INTERVAL  = 2
SEND_INTERVAL       = 10
HEARTBEAT_INTERVAL  = 15
FEDERATION_INTERVAL = 120

# ── Anomaly thresholds ────────────────────
TEMP_MIN = 4.0
TEMP_MAX = 35.0
PH_MIN = 6.0
PH_MAX = 9.0
TURBIDITY_MIN = 0.0
TURBIDITY_MAX = 500.0

# ── Time-series anomaly detection ─────────
ANOMALY_WINDOW      = 30
ANOMALY_Z_THRESHOLD = 2.5
ANOMALY_TEMP_SPIKE  = 5.0
ANOMALY_PH_SPIKE    = 1.0
ANOMALY_TURB_SPIKE  = 100.0
ANOMALY_EWMA_ALPHA  = 0.3
