# Configuration for Raspberry Pi 4 Edge Node
# ───────────────────────────────────────────
# ARCHITECTURE (per patent disclosure):
#   ESP32-S3  --local WiFi/MQTT-->  Pi4 (this node, Mosquitto broker)
#   Pi4 (edge)  --MQTT/TLS-->  HiveMQ Cloud  <--MQTT/TLS--  Pi5 (central)
# The ESP32 <-> Pi4 hop stays on local WiFi (sensors are physically next to
# the node). The Pi4 <-> Pi5 hop goes over HiveMQ Cloud so a node can be
# placed anywhere on the river without needing to be on the same LAN as Pi5.
#
# INSTRUCTIONS:
#   1. Create a free/paid cluster at https://console.hivemq.cloud
#   2. Copy the Cluster URL, and create a device username/password under
#      "Access Management" -> paste them below.
# ───────────────────────────────────────────

# ── Node identity ──────────────────────────
NODE_ID  = "pi4_edge_01"          # unique per zone, e.g. pi4_edge_zone2
ZONE_ID  = "zone_1"

# ── Local MQTT (Mosquitto on THIS Pi4, ESP32 connects here) ──
MQTT_BROKER = "localhost"            # ESP32 publishes to this Pi4's IP
MQTT_PORT   = 1883
MQTT_TOPIC_DATA   = "river/sensor_data"
MQTT_TOPIC_STATUS = "river/status"

# ── HiveMQ Cloud (long-range Pi4 <-> Pi5 link) ────────────
HIVEMQ_HOST = "e7aa014fd5fe4eefb78c336a540b2d00.s1.eu.hivemq.cloud:8883"   # ← your cluster URL
HIVEMQ_PORT = 8883                                 # TLS port
HIVEMQ_USERNAME = "river_edge_client"               # ← device credential
HIVEMQ_PASSWORD = "12345678"                       # ← device credential
HIVEMQ_USE_TLS  = True
HIVEMQ_KEEPALIVE = 60
HIVEMQ_CLIENT_ID = f"{NODE_ID}_hivemq"
HIVEMQ_QOS = 1
HIVEMQ_MAX_PAYLOAD_BYTES = 20 * 1024 * 1024

# Topic namespace: river/{zone}/...
HIVEMQ_TOPIC_PREFIX          = f"river/{ZONE_ID}"
HIVEMQ_TOPIC_REGISTER        = f"{HIVEMQ_TOPIC_PREFIX}/register"
HIVEMQ_TOPIC_HEARTBEAT       = f"{HIVEMQ_TOPIC_PREFIX}/heartbeat"
HIVEMQ_TOPIC_DATA_SUBMIT     = f"{HIVEMQ_TOPIC_PREFIX}/data"
HIVEMQ_TOPIC_FED_SUBMIT      = f"{HIVEMQ_TOPIC_PREFIX}/federation/submit"
HIVEMQ_TOPIC_FED_GLOBAL      = f"{HIVEMQ_TOPIC_PREFIX}/federation/global"   # Pi5 -> Pi4
HIVEMQ_TOPIC_LABEL_PROPOSAL  = f"{HIVEMQ_TOPIC_PREFIX}/label_discovery/proposal"
HIVEMQ_TOPIC_LABEL_REGISTRY  = "river/label_registry/global"                 # shared across all zones

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
# NOTE: this list is mutated at runtime by label_discovery.py when a new
# "unknown_label_N" class is promoted, so both the detector and the
# federated head must be able to grow an extra output class.

# ── Autonomous Waste Label Discovery ─────
# A detection is a "candidate unknown" when its best class confidence sits
# BELOW this bar (model isn't sure it's any known class) but still above a
# noise floor so pure background isn't clustered.
UNKNOWN_CONF_LOW   = 0.10   # noise floor — ignore below this
UNKNOWN_CONF_HIGH  = 0.45   # below this = "unknown" (disclosure range 0.30-0.60)

# Visual-similarity clustering of unknown crops
LABEL_DISCOVERY_SIMILARITY_THRESHOLD = 0.85   # cosine similarity to join a cluster
LABEL_DISCOVERY_FREQUENCY_THRESHOLD  = 15     # occurrences before a cluster becomes a new label (disclosure range 10-100)
LABEL_DISCOVERY_MAX_BUFFER           = 500    # cap on stored unknown crops (memory bound on Pi4)
LABEL_DISCOVERY_CROP_SIZE            = 64     # unknown crops resized to this for cheap feature hashing
LABEL_DISCOVERY_PREFIX               = "unknown_label_"
LABEL_DISCOVERY_SAMPLES_DIR          = "unknown_samples"   # crops saved here for later annotation/training

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