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

    while running:
        now = time.time()

        # Heartbeat
        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            fc.heartbeat()
            last_hb = now

        # Send data
        if now - last_send >= config.SEND_INTERVAL:
            data = sensor.get_aggregated()
            anomalies = sensor.detect_anomalies(data)
            fc.send_data(data, latest_detection, anomalies)
            last_send = now
            log.info("Data sent to Pi5")

        time.sleep(1)


def main():
    log.info("=== Pi4 Edge Node starting ===")

    # 1. Register with Pi5
    fc.register()

    # 2. Start MQTT subscriber
    sensor.start()

    # 3. Load YOLOv8 model & open camera
    detector.load_model()
    detector.open_camera()

    # 4. Launch threads
    threads = [
        threading.Thread(target=sensor_loop, daemon=True),
        threading.Thread(target=detection_loop, daemon=True),
        threading.Thread(target=communication_loop, daemon=True),
    ]
    for t in threads:
        t.start()

    log.info("All threads running. Press Ctrl+C to stop.")

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
