"""
Main entry point for the Pi4 Edge Node.

Runs four background loops:
  1. Sensor polling    — MQTT data from ESP32 via HiveMQ cloud
  2. Trash detection   — YOLOv8 on Pi Camera V2 frames
  3. Communication     — sends data to Pi5 central server
  4. Federation        — participates in federated learning rounds

NEW: Unknown Object Discovery loop
  5. Autonomous waste discovery — flags low-confidence detections,
     clusters similar unknowns, auto-labels and publishes to dashboard
"""

import time
import logging
import threading

import config
from sensor_reader import SensorReader
from trash_detector import TrashDetector
from anomaly_detector import AnomalyDetector
from unknown_object_tracker import UnknownObjectTracker
import federated_client as fc

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("edge")

# ── Shared state ──────────────────────────────────────────────
sensor       = SensorReader()
detector     = TrashDetector()
anomaly_det  = AnomalyDetector()
unknown_tracker = UnknownObjectTracker()

latest_detection = {"trash_count": 0, "detections": [], "class_counts": {}}
running = True


def sensor_loop():
    """Poll HiveMQ cloud MQTT data at regular intervals."""
    connect_attempts = 0
    max_retries = 5
    retry_delay = 2

    while running:
        try:
            if not sensor.connected:
                connect_attempts += 1
                if connect_attempts <= max_retries:
                    log.warning("⚠ HiveMQ MQTT not connected yet "
                                "(attempt %d/%d), retrying in %ds...",
                                connect_attempts, max_retries, retry_delay)
                    time.sleep(retry_delay)
                    continue
                elif connect_attempts == max_retries + 1:
                    log.error("✗ HiveMQ connection failed after %d attempts", max_retries)
                    log.error("  → Check MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD in config.py")
                    connect_attempts += 1
            else:
                connect_attempts = 0

            data = sensor.get_aggregated()
            if data["node_count"] > 0:
                log.info("📊 Sensors — temp=%.1f°C  pH=%.2f  turb=%.0f NTU  nodes=%d",
                         data["temperature"], data["ph"],
                         data.get("turbidity", 0), data["node_count"])
            else:
                log.debug("⏳ No sensor data yet (waiting for ESP32 via HiveMQ...)")
        except Exception as e:
            log.error("✗ Sensor loop error: %s", e)

        time.sleep(config.SENSOR_POLL)


def detection_loop():
    """Capture frames from Pi Camera V2, run YOLOv8, flag unknowns."""
    global latest_detection
    model_ready  = False
    camera_ready = False
    startup_logged = False

    while running:
        try:
            if not startup_logged:
                model_ready  = detector.model is not None or detector.cv_net is not None
                camera_ready = detector.camera

                if not model_ready:
                    log.warning("⚠ Model not loaded, detection disabled")
                if not camera_ready:
                    log.warning("⚠ Camera not ready, detection disabled")

                if model_ready and camera_ready:
                    log.info("✓ Model: %s | Camera: Ready",
                             detector.model_type or "OpenCV DNN")
                    startup_logged = True

            if not (model_ready and camera_ready):
                time.sleep(config.DETECTION_INTERVAL)
                continue

            # ── Run YOLO detection ────────────────────────────
            result = detector.detect()
            latest_detection = result

            if result["trash_count"] > 0:
                log.info("🗑️  Trash detected: %d items — %s",
                         result["trash_count"], result["class_counts"])

                # ── Unknown object check ──────────────────────
                # Collect raw confidence scores from detections
                raw_scores = [
                    d.get("confidence", 1.0)
                    for d in result.get("detections", [])
                ]

                # Get current frame for unknown tracker
                try:
                    frame = detector._capture_frame()
                    unknown_result = unknown_tracker.process_frame(frame, raw_scores)

                    if unknown_result["unknown_detected"]:
                        log.info("❓ Unknown object detected "
                                 "(total unknowns: %d)",
                                 unknown_result["total_unknown"])

                    if unknown_result["new_label_created"]:
                        new_label = unknown_result["new_label"]
                        log.info("🆕 Auto-label created: %s — notifying Pi5", new_label)
                        # Notify Pi5 server about new discovered label
                        fc.send_unknown_label_event(
                            label=new_label,
                            cluster_id="auto",
                            sighting_count=config.UNKNOWN_CLUSTER_THRESHOLD,
                        )
                except Exception as e:
                    log.debug("⚠ Unknown tracker frame capture failed: %s", e)
            else:
                log.debug("✓ Detection passed: no trash")

        except Exception as e:
            log.error("✗ Detection loop error: %s", e)

        time.sleep(config.DETECTION_INTERVAL)


def communication_loop():
    """Periodically send aggregated data + detections to Pi5."""
    last_send  = 0
    last_hb    = 0
    registered = False
    reg_attempts = 0
    max_reg_retries = 3

    while running:
        now = time.time()

        if not registered:
            reg_attempts += 1
            registered = fc.register()
            if not registered:
                if reg_attempts <= max_reg_retries:
                    log.warning("⚠ Pi5 registration pending "
                                "(attempt %d/%d) — retry in 10s",
                                reg_attempts, max_reg_retries)
                elif reg_attempts == max_reg_retries + 1:
                    log.error("✗ Cannot reach Pi5 at %s!", config.SERVER_URL)
                    log.error("  → Verify PI5_IP in config.py")
                    reg_attempts += 1
                time.sleep(10)
                continue
            else:
                reg_attempts = 0
                log.info("✓ Pi5 registration complete")

        # Heartbeat
        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            if not fc.heartbeat():
                log.warning("⚠ Heartbeat failed")
            last_hb = now

        # Send sensor + detection + anomaly data
        if now - last_send >= config.SEND_INTERVAL:
            data = sensor.get_aggregated()

            if data.get("node_count", 0) > 0:
                anomalies = anomaly_det.update(
                    temperature=data.get("temperature", 0),
                    ph=data.get("ph", 7),
                    turbidity=data.get("turbidity", 0),
                )
            else:
                anomalies = {
                    "temperature": False, "ph": False, "turbidity": False,
                    "anomaly_detected": False, "anomaly_list": [],
                    "total_anomalies": anomaly_det.total_anomalies,
                    "stats": {"temperature": None, "ph": None, "turbidity": None},
                }

            # Attach unknown tracker summary to detection result
            detection_payload = dict(latest_detection)
            detection_payload["unknown_summary"] = unknown_tracker.get_summary()

            sent = fc.send_data(data, detection_payload, anomalies)
            if sent:
                last_send = now
                log.info("📤 Sent → Pi5  temp=%.1f°C  pH=%.2f  turb=%.0f  "
                         "trash=%d  anomalies=%d  unknowns=%d",
                         data.get("temperature", 0), data.get("ph", 0),
                         data.get("turbidity", 0),
                         latest_detection.get("trash_count", 0),
                         len(anomalies.get("anomaly_list", [])),
                         unknown_tracker.total_unknown)
            else:
                log.warning("⚠ Failed to send data to Pi5")

        time.sleep(1)


def federation_loop():
    """Periodically participate in federated learning rounds.
    
    Only detection-head parameters are exchanged — not the full model.
    This matches the paper's FL privacy claim and reduces bandwidth.
    """
    last_round     = 0
    startup_shown  = False

    # Wait for model
    while running and detector.model is None and detector.cv_net is None:
        if not startup_shown:
            log.info("⏳ Waiting for model (federation on hold)...")
            startup_shown = True
        time.sleep(5)

    if running:
        log.info("✓ Federation loop started (interval=%ds)",
                 config.FEDERATION_INTERVAL)

    # YOLOv8 detection-head layer names to filter
    # Only these layers are sent — backbone stays local
    DETECT_HEAD_LAYERS = ["cv2", "cv3", "dfl"]

    while running:
        try:
            time.sleep(config.FEDERATION_INTERVAL)

            if detector.model_type == "cv_dnn":
                log.debug("ℹ OpenCV DNN: federation not supported")
                continue

            # 1. Extract detection-head weights only
            weights = detector.get_head_weights()
            if weights is None:
                log.debug("ℹ No weights available for federation")
                continue

            # 2. Submit detection-head only (backbone excluded)
            if not fc.submit_update(weights, layer_names=DETECT_HEAD_LAYERS):
                log.warning("⚠ Federation: weight submission failed")
                continue

            # 3. Fetch and apply global aggregated weights
            global_data = fc.get_global_weights()
            if global_data and global_data.get("weights"):
                new_round = global_data.get("round", 0)
                if new_round > last_round:
                    detector.apply_head_weights(global_data["weights"])
                    last_round = new_round
                    log.info("🔄 Federation round %d applied", new_round)
                else:
                    log.debug("ℹ Still on round %d", last_round)
            else:
                log.debug("ℹ No global weights available yet")

        except Exception as e:
            log.error("✗ Federation loop error: %s", e)


def main():
    log.info("=" * 60)
    log.info("🚀 Pi4 Edge Node starting...")
    log.info("=" * 60)
    log.info("HiveMQ broker : %s:%d", config.MQTT_BROKER, config.MQTT_PORT)
    log.info("Pi5 server    : %s",    config.SERVER_URL)
    log.info("Node ID       : %s",    config.NODE_ID)

    if "YOUR_CLUSTER" in config.MQTT_BROKER:
        log.error("❌ config.py still has placeholder MQTT_BROKER!")
        log.error("   Sign up at hivemq.com and update MQTT_BROKER, "
                  "MQTT_USERNAME, MQTT_PASSWORD")
        return

    log.info("-" * 60)
    log.info("[1/4] Connecting to HiveMQ cloud MQTT...")
    sensor.start()
    time.sleep(2)

    log.info("-" * 60)
    log.info("[2/4] Loading YOLOv8 model...")
    model_ok = detector.load_model()
    if not model_ok:
        log.error("❌ Model failed — check best.pt / best.onnx path")
    else:
        log.info("✓ Model loaded")

    log.info("-" * 60)
    log.info("[3/4] Initialising Pi Camera V2...")
    camera_ok = detector.open_camera()
    if not camera_ok:
        log.error("❌ Camera failed — check libcamera / picamera2 installation")
    else:
        log.info("✓ Camera ready via: %s", detector.camera_method)

    log.info("-" * 60)
    log.info("[4/4] Launching background threads...")

    threads = [
        threading.Thread(target=sensor_loop,        daemon=True, name="sensor"),
        threading.Thread(target=detection_loop,     daemon=True, name="detection"),
        threading.Thread(target=communication_loop, daemon=True, name="comms"),
        threading.Thread(target=federation_loop,    daemon=True, name="federation"),
    ]
    for t in threads:
        t.start()
        log.info("  ✓ Thread: %s", t.name)

    log.info("=" * 60)
    log.info("✓ All systems ready. Press Ctrl+C to shutdown.")
    log.info("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        global running
        running = False
        log.info("\n" + "=" * 60)
        log.info("⏹️  Shutting down...")
        time.sleep(2)
        sensor.stop()
        detector.release()
        unknown_tracker.stop()
        log.info("✓ Shutdown complete")


if __name__ == "__main__":
    main()
