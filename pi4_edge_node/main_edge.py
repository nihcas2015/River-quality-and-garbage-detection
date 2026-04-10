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
    connect_attempts = 0
    max_retries = 5
    retry_delay = 2  # seconds
    
    while running:
        try:
            if not sensor.connected:
                connect_attempts += 1
                if connect_attempts <= max_retries:
                    log.warning("⚠ MQTT not connected yet (attempt %d/%d), retrying in %ds...",
                               connect_attempts, max_retries, retry_delay)
                    time.sleep(retry_delay)
                    continue
                else:
                    if connect_attempts == max_retries + 1:
                        log.error("✗ MQTT connection failed after %d attempts", max_retries)
                        log.error("  → Check if Mosquitto is running on localhost:1883")
                        log.error("  → Run: 'sudo systemctl start mosquitto'")
                        connect_attempts += 1  # prevents repeating error message
            else:
                connect_attempts = 0  # reset on successful connection
            
            data = sensor.get_aggregated()
            if data["node_count"] > 0:
                log.info("📊 Sensors — temp=%.1f°C  pH=%.2f  turb=%.0f NTU  nodes=%d",
                         data["temperature"], data["ph"],
                         data.get("turbidity", 0), data["node_count"])
            else:
                log.debug("⏳ No sensor data received yet (waiting for ESP32...)")
        except Exception as e:
            log.error("✗ Sensor loop error: %s", e)
        
        time.sleep(config.SENSOR_POLL)


def detection_loop():
    """Capture frames from Pi Camera V2 and run YOLOv8."""
    global latest_detection
    model_ready = False
    camera_ready = False
    startup_logged = False
    
    while running:
        try:
            # Check initialization status on first run
            if not startup_logged:
                model_ready = detector.model is not None or detector.cv_net is not None
                camera_ready = detector.camera
                
                if not model_ready:
                    log.warning("⚠ Model not loaded, detection disabled")
                if not camera_ready:
                    log.warning("⚠ Camera not ready, detection disabled")
                
                if model_ready and camera_ready:
                    log.info("✓ Model: %s | Camera: Ready", detector.model_type or "OpenCV DNN")
                    startup_logged = True
            
            # Only run detection if both model and camera are ready
            if not (model_ready and camera_ready):
                time.sleep(config.DETECTION_INTERVAL)
                continue
            
            result = detector.detect()
            latest_detection = result
            
            if result["trash_count"] > 0:
                log.info("🗑️  Trash detected: %d items — %s",
                        result["trash_count"], result["class_counts"])
            else:
                log.debug("✓ Detection passed: no trash")
        except Exception as e:
            log.error("✗ Detection loop error: %s", e)
        
        time.sleep(config.DETECTION_INTERVAL)


def communication_loop():
    """Periodically send aggregated data + detections to Pi5."""
    last_send = 0
    last_hb = 0
    registered = False
    registration_attempts = 0
    max_registration_retries = 3

    while running:
        now = time.time()

        # Retry registration until it succeeds
        if not registered:
            registration_attempts += 1
            registered = fc.register()
            if not registered:
                if registration_attempts <= max_registration_retries:
                    log.warning("⚠ Pi5 registration pending (attempt %d/%d) — will retry in 10s",
                               registration_attempts, max_registration_retries)
                else:
                    if registration_attempts == max_registration_retries + 1:
                        log.error("✗ Cannot reach Pi5 at %s!", config.SERVER_URL)
                        log.error("  → Check IP: %s", config.PI5_IP)
                        log.error("  → Check connectivity: 'ping %s'", config.PI5_IP)
                        registration_attempts += 1
                
                time.sleep(10)
                continue
            else:
                registration_attempts = 0
                log.info("✓ Pi5 registration complete")

        # Heartbeat
        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            if not fc.heartbeat():
                log.warning("⚠ Heartbeat failed")
            last_hb = now

        # Send data
        if now - last_send >= config.SEND_INTERVAL:
            data = sensor.get_aggregated()
            # Run time-series anomaly detection (only with real sensor data)
            if data.get("node_count", 0) > 0:
                anomalies = anomaly_det.update(
                    temperature=data.get("temperature", 0),
                    ph=data.get("ph", 7),
                    turbidity=data.get("turbidity", 0),
                )
            else:
                anomalies = {"temperature": False, "ph": False,
                             "turbidity": False,
                             "anomaly_detected": False, "anomaly_list": [],
                             "total_anomalies": anomaly_det.total_anomalies,
                             "stats": {"temperature": None, "ph": None,
                                       "turbidity": None}}
            
            sent = fc.send_data(data, latest_detection, anomalies)
            if sent:
                last_send = now
                log.info("📤 Data sent → Pi5  |  temp=%.1f°C  pH=%.2f  turb=%.0f NTU  trash=%d  anomalies=%d",
                         data.get("temperature", 0), data.get("ph", 0),
                         data.get("turbidity", 0),
                         latest_detection.get("trash_count", 0),
                         len(anomalies.get("anomaly_list", [])))
            else:
                log.warning("⚠ Failed to send data to Pi5")

        time.sleep(1)


def federation_loop():
    """Periodically participate in federated learning rounds."""
    last_round = 0
    startup_msg_shown = False

    # Wait for model to be ready
    while running and detector.model is None and detector.cv_net is None:
        if not startup_msg_shown:
            log.info("⏳ Waiting for model to load (federation on hold)...")
            startup_msg_shown = True
        time.sleep(5)

    if running:
        log.info("✓ Federation loop started (interval=%ds)", config.FEDERATION_INTERVAL)

    while running:
        try:
            time.sleep(config.FEDERATION_INTERVAL)

            # Only supported with PyTorch models
            if detector.model_type == "cv_dnn":
                log.debug("ℹ OpenCV DNN backend: federation weights not supported")
                continue
            
            # 1. Extract local detection-head weights
            weights = detector.get_head_weights()
            if weights is None:
                log.debug("ℹ Federation: no model weights available (using DNN or ONNX?)")
                continue

            # 2. Send local update to Pi5
            if not fc.submit_update(weights):
                log.warning("⚠ Federation: failed to submit weights")
                continue

            # 3. Fetch global aggregated weights
            global_data = fc.get_global_weights()
            if global_data and global_data.get("weights"):
                new_round = global_data.get("round", 0)
                if new_round > last_round:
                    detector.apply_head_weights(global_data["weights"])
                    last_round = new_round
                    log.info("🔄 Federation: applied global model (round %d)", new_round)
                else:
                    log.debug("ℹ Federation: still on round %d", last_round)
            else:
                log.debug("ℹ Federation: no global weights available yet")
        except Exception as e:
            log.error("✗ Federation loop error: %s", e)


def main():
    log.info("="*60)
    log.info("🚀 Pi4 Edge Node starting...")
    log.info("="*60)
    log.info("Target Pi5 server: %s", config.SERVER_URL)
    log.info("MQTT broker: %s:%d", config.MQTT_BROKER, config.MQTT_PORT)
    log.info("MQTT topics: %s (data), %s (status)", 
             config.MQTT_TOPIC_DATA, config.MQTT_TOPIC_STATUS)
    log.info("Node ID: %s", config.NODE_ID)

    # Validation checks
    if "<PI5_IP>" in config.SERVER_URL:
        log.error("❌ config.py still has placeholder <PI5_IP>!")
        log.error("   Run 'hostname -I' on your Pi5 and update config.SERVER_URL")
        return
    
    log.info("-"*60)
    log.info("[1/4] Starting MQTT broker connection...")
    log.info("-"*60)
    
    # 1. Start MQTT subscriber
    sensor.start()
    time.sleep(1)
    
    log.info("-"*60)
    log.info("[2/4] Loading YOLOv8 model...")
    log.info("-"*60)
    
    # 2. Load YOLOv8 model & open camera
    model_ok = detector.load_model()
    if not model_ok:
        log.error("❌ YOLOv8 model failed to load")
        log.error("   Check if best.pt or best.onnx exists in the current directory")
    else:
        log.info("✓ Model loaded successfully")
    
    log.info("-"*60)
    log.info("[3/4] Initializing Pi Camera V2...")
    log.info("-"*60)
    
    camera_ok = detector.open_camera()
    if not camera_ok:
        log.error("❌ Pi Camera failed to open")
        log.error("   Options:")
        log.error("   1. Install picamera2: pip install picamera2")
        log.error("   2. Install libcamera: sudo apt install -y libcamera-tools")
        log.error("   3. Check: libcamera-hello --list-cameras")
    else:
        log.info("✓ Camera initialized via: %s", detector.camera_method)
    
    log.info("-"*60)
    log.info("[4/4] Launching background threads...")
    log.info("-"*60)
    
    # 3. Launch threads
    threads = [
        threading.Thread(target=sensor_loop, daemon=True, name="sensor"),
        threading.Thread(target=detection_loop, daemon=True, name="detection"),
        threading.Thread(target=communication_loop, daemon=True, name="comms"),
        threading.Thread(target=federation_loop, daemon=True, name="federation"),
    ]
    for t in threads:
        t.start()
        log.info("  ✓ Started thread: %s", t.name)

    log.info("="*60)
    log.info("✓ All systems ready. Press Ctrl+C to shutdown.")
    log.info("="*60)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        global running
        running = False
        log.info("\n"+"="*60)
        log.info("⏹️  Shutting down gracefully...")
        log.info("="*60)
        time.sleep(2)
        sensor.stop()
        detector.release()
        log.info("✓ Shutdown complete")


if __name__ == "__main__":
    main()
