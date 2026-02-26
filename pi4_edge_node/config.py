# Configuration for Raspberry Pi 4 Edge Node

# Pi5 Central Server
SERVER_URL = "http://192.168.1.100:5000"  # Change to your Pi5 IP
NODE_ID = "pi4_edge_01"

# MQTT (Mosquitto runs on this Pi4)
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "river/sensor_data"
MQTT_TOPIC_STATUS = "river/status"

# Pi Camera V2 (via Picamera2)
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# YOLOv8 Model
MODEL_PATH = "best.pt"
CONFIDENCE = 0.5

# Timing (seconds)
SENSOR_POLL = 5
DETECTION_INTERVAL = 2
SEND_INTERVAL = 10
HEARTBEAT_INTERVAL = 15
FEDERATION_INTERVAL = 120   # seconds between federated learning rounds

# Anomaly thresholds (absolute bounds)
TEMP_MIN = 4.0
TEMP_MAX = 35.0
PH_MIN = 6.0
PH_MAX = 9.0
TURBIDITY_MIN = 0.0
TURBIDITY_MAX = 1000.0      # NTU — rivers can naturally reach ~1000

# Time-series anomaly detection
ANOMALY_WINDOW = 30           # sliding window size (number of readings)
ANOMALY_Z_THRESHOLD = 2.5     # Z-score to flag a statistical outlier
ANOMALY_TEMP_SPIKE = 5.0      # °C change in one reading = spike
ANOMALY_PH_SPIKE = 1.0        # pH change in one reading  = spike
ANOMALY_TURB_SPIKE = 200.0    # NTU change in one reading  = spike
ANOMALY_EWMA_ALPHA = 0.3      # EWMA smoothing factor (0–1, higher = more reactive)
