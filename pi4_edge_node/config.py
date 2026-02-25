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

# Anomaly thresholds
TEMP_MIN = 4.0
TEMP_MAX = 35.0
PH_MIN = 6.0
PH_MAX = 9.0
