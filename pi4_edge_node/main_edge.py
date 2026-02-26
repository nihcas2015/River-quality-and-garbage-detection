"""
Main entry point for the Pi4 Edge Node.
Runs three background loops:
  1. Sensor polling  (MQTT data from ESP32)
  2. Trash detection (YOLOv8 on Pi Camera V2 frames)
  3. Communication   (sends data to Pi5 central server)
"""

import time
import logging
import threading

import config
from sensor_reader import SensorReader
from trash_detector import TrashDetector
from anomaly_detector import AnomalyDetector
import federated_client as fc

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("edge")

# ── Shared state ─────────────────────────────────────────────
sensor = SensorReader()
detector = TrashDetector()
anomaly_det = AnomalyDetector()
latest_detection = {"trash_count": 0, "detections": []}
running = True


def sensor_loop():
    """Poll MQTT data at regular intervals (logging only)."""
    while running:
        data = sensor.get_aggregated()
        if data["node_count"] > 0:
            log.info("Sensors — temp=%.1f°C  pH=%.2f  nodes=%d",
                     data["temperature"], data["ph"], data["node_count"])
        time.sleep(config.SENSOR_POLL)


def detection_loop():
    """Capture frames from Pi Camera V2 and run YOLOv8."""
    global latest_detection
    while running:
        result = detector.detect()
        latest_detection = result
        if result["trash_count"] > 0:
            log.info("Trash detected: %d items", result["trash_count"])
        time.sleep(config.DETECTION_INTERVAL)


def communication_loop():
    """Periodically send aggregated data + detections to Pi5."""
    last_send = 0
    last_hb = 0
    registered = False

    while running:
        now = time.time()

        # Retry registration until it succeeds
        if not registered:
            registered = fc.register()
            if not registered:
                log.warning("Pi5 registration pending — will retry in 10 s")
                time.sleep(10)
                continue

        # Heartbeat
        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            fc.heartbeat()
            last_hb = now

        # Send data
        if now - last_send >= config.SEND_INTERVAL:
            data = sensor.get_aggregated()
            # Run time-series anomaly detection (only with real sensor data)
            if data.get("node_count", 0) > 0:
                anomalies = anomaly_det.update(
                    temperature=data.get("temperature", 0),
                    ph=data.get("ph", 7),
                )
            else:
                anomalies = {"temperature": False, "ph": False,
                             "anomaly_detected": False, "anomaly_list": [],
                             "total_anomalies": anomaly_det.total_anomalies,
                             "stats": {"temperature": None, "ph": None}}
            fc.send_data(data, latest_detection, anomalies)
            last_send = now
            log.info("Data sent to Pi5  |  temp=%.1f  pH=%.2f  trash=%d  anomalies=%d",
                     data.get("temperature", 0), data.get("ph", 0),
                     latest_detection.get("trash_count", 0),
                     len(anomalies.get("anomaly_list", [])))

        time.sleep(1)


def federation_loop():
    """Periodically participate in federated learning rounds."""
    last_round = 0

    # Wait for model to be ready
    while running and detector.model is None:
        time.sleep(5)

    log.info("Federation loop started (interval=%ds)", config.FEDERATION_INTERVAL)

    while running:
        time.sleep(config.FEDERATION_INTERVAL)

        # 1. Extract local detection-head weights
        weights = detector.get_head_weights()
        if weights is None:
            log.warning("Federation: no model weights available")
            continue

        # 2. Send local update to Pi5
        if not fc.submit_update(weights):
            log.warning("Federation: failed to submit update")
            continue

        # 3. Fetch global aggregated weights
        global_data = fc.get_global_weights()
        if global_data and global_data.get("weights"):
            new_round = global_data.get("round", 0)
            if new_round > last_round:
                detector.apply_head_weights(global_data["weights"])
                last_round = new_round
                log.info("Federation: applied global model (round %d)", new_round)
            else:
                log.debug("Federation: still on round %d", last_round)


def main():
    log.info("=== Pi4 Edge Node starting ===")
    log.info("Target Pi5 server: %s", config.SERVER_URL)

    if "<PI5_IP>" in config.SERVER_URL:
        log.error("config.py still has placeholder <PI5_IP>! "
                  "Run 'hostname -I' on your Pi5 and update SERVER_URL.")
        return

    # 1. Start MQTT subscriber
    sensor.start()

    # 2. Load YOLOv8 model & open camera
    model_ok = detector.load_model()
    camera_ok = detector.open_camera()
    if not model_ok:
        log.error("YOLOv8 model failed to load — detection & federation disabled")
    if not camera_ok:
        log.error("Pi Camera failed to open — detection disabled")

    # 3. Launch threads
    threads = [
        threading.Thread(target=sensor_loop, daemon=True, name="sensor"),
        threading.Thread(target=detection_loop, daemon=True, name="detection"),
        threading.Thread(target=communication_loop, daemon=True, name="comms"),
        threading.Thread(target=federation_loop, daemon=True, name="federation"),
    ]
    for t in threads:
        t.start()
        log.info("Started thread: %s", t.name)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        global running
        running = False
        log.info("Shutting down...")
        sensor.stop()
        detector.release()


if __name__ == "__main__":
    main()
