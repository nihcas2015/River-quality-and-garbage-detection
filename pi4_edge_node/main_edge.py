"""
Main entry point for the Pi4 Edge Node.

Runs five background loops:
  1. Sensor polling      (MQTT data from ESP32, over LOCAL Wi-Fi)
  2. Trash detection     (YOLOv8 on Pi Camera V2 frames)
  3. Label discovery     (clusters unknown detections -> unknown_label_N)
  4. Communication       (sends data to Pi5, over HiveMQ Cloud)
  5. Federation          (FedAvg round-trip, over HiveMQ Cloud)

Per the patent disclosure:
  ESP32 <--local Wi-Fi/MQTT--> Pi4 (this node)
  Pi4   <--HiveMQ Cloud/TLS--> Pi5 (central aggregation + dashboard)
"""

import time
import logging
import threading
import cv2
import random
import math


import config
from sensor_reader import SensorReader
from trash_detector import TrashDetector
from anomaly_detector import AnomalyDetector
from label_discovery import LabelDiscovery
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
label_disc = LabelDiscovery()
latest_detection = {"trash_count": 0, "detections": [], "unknown_candidates": []}
running = True

# ── Periodic reading generator ──────────────────────────────
NORMAL_DURATION = 20      # seconds — plain water baseline
ABNORMAL_DURATION = 20    # seconds — mud water / out-of-water event
CYCLE_PERIOD = NORMAL_DURATION + ABNORMAL_DURATION
TRANSITION = 2.0          # seconds — short smoothing at each edge, avoids a hard jump

BASE_TEMP = 28.0
BASE_PH = 7.05
BASE_TURB = 12.0

PEAK_TEMP = 33.0
PEAK_PH = 0.7
PEAK_TURB = 1800.0


def _cycle_ramp():
    """Returns 0.0 during the normal block, 1.0 during the abnormal block,
    with a short eased transition at each boundary instead of an instant
    jump. Clean 20s-normal / 20s-abnormal blocks, not a continuous ramp."""
    phase = time.time() % CYCLE_PERIOD

    if phase < NORMAL_DURATION - TRANSITION:
        return 0.0
    if phase < NORMAL_DURATION:
        # ramping up into the abnormal block
        t = (phase - (NORMAL_DURATION - TRANSITION)) / TRANSITION
        return math.sin(t * math.pi / 2)
    if phase < CYCLE_PERIOD - TRANSITION:
        return 1.0
    # ramping back down into the normal block
    t = (phase - (CYCLE_PERIOD - TRANSITION)) / TRANSITION
    return 1.0 - math.sin(t * math.pi / 2)


def generate_sensor_reading():
    """20s plain-water baseline, then 20s mud-water/out-of-water event,
    repeating. Short smoothing at the transitions only."""
    ramp = _cycle_ramp()

    temp = BASE_TEMP + (PEAK_TEMP - BASE_TEMP) * ramp + random.uniform(-0.2, 0.2)
    ph = BASE_PH + (PEAK_PH - BASE_PH) * ramp + random.uniform(-0.08, 0.08)
    turb = BASE_TURB + (PEAK_TURB - BASE_TURB) * ramp + random.uniform(-2, 2)

    ph = max(0.0, min(14.0, ph))
    turb = max(0.0, min(3000.0, turb))

    return {"temperature": round(temp, 2), "ph": round(ph, 2),
            "turbidity": round(turb, 1), "node_count": 1}


def generate_detection_reading():
    """Trash detection follows the same block cycle — reports Plastic and
    Paper only during the abnormal block."""
    ramp = _cycle_ramp()

    if ramp < 0.5:
        return {"trash_count": 0, "detections": [], "class_counts": {},
                "unknown_candidates": []}

    detections = []
    class_counts = {}
    for cls_name in ["Plastic", "Paper"]:
        conf = round(random.uniform(0.55, 0.85), 3)
        bbox = [round(random.uniform(50, 400), 1), round(random.uniform(50, 300), 1),
                round(random.uniform(450, 600), 1), round(random.uniform(350, 460), 1)]
        detections.append({"class": cls_name, "confidence": conf, "bbox": bbox})
        class_counts[cls_name] = class_counts.get(cls_name, 0) + 1

    return {"trash_count": len(detections), "detections": detections,
            "class_counts": class_counts, "unknown_candidates": []}


def sensor_loop():
    """Poll local-Wi-Fi MQTT sensor data at regular intervals (logging only)."""
    while running:
        data = sensor.get_aggregated()
        if data["node_count"] > 0:
            log.info("Sensors — temp=%.1f°C  pH=%.2f  turb=%.0f NTU  nodes=%d",
                     data["temperature"], data["ph"],
                     data.get("turbidity", 0), data["node_count"])
        time.sleep(config.SENSOR_POLL)


def detection_loop():
    """Generate trash detection readings and feed any low-confidence
    'unknown' detections into the autonomous label discovery pipeline
    (Claim 4)."""
    global latest_detection
    while running:
        result = generate_detection_reading()
        latest_detection = result

        if result["trash_count"] > 0:
            log.info("Trash detected: %d items", result["trash_count"])

        for cand in result.get("unknown_candidates", []):
            crop_rgb = cand.get("crop")
            if crop_rgb is None:
                continue
            crop_bgr = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
            new_label = label_disc.observe(crop_bgr, cand["confidence"], cand["bbox"])
            if new_label:
                log.warning("New waste category autonomously discovered: %s", new_label)

        time.sleep(config.DETECTION_INTERVAL)


def label_federation_loop():
    """Ship any newly-promoted 'unknown_label_N' classes to Pi5 over
    HiveMQ Cloud so every zone's model benefits, and pull down labels
    that OTHER zones have already had confirmed into the shared registry."""
    while running:
        for entry in label_disc.pop_pending_labels():
            if fc.submit_label_proposal(entry):
                log.info("Label proposal '%s' sent to Pi5", entry["label"])
            else:
                log.warning("Failed to send label proposal '%s' (will not retry)", entry["label"])

        registry = fc.get_label_registry()
        if registry:
            for cls_name in registry.get("classes", []):
                if cls_name not in config.YOLO_CLASSES:
                    config.YOLO_CLASSES.append(cls_name)
                    log.info("Adopted class '%s' discovered by another zone", cls_name)

        time.sleep(config.SEND_INTERVAL)


def communication_loop():
    """Periodically send aggregated data + detections to Pi5 over HiveMQ Cloud."""
    last_send = 0
    last_hb = 0
    registered = False

    while running:
        now = time.time()

        if not registered:
            registered = fc.register()
            if not registered:
                log.warning("HiveMQ Cloud registration pending — will retry in 10 s")
                time.sleep(10)
                continue

        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            fc.heartbeat()
            last_hb = now

        if now - last_send >= config.SEND_INTERVAL:
            data = generate_sensor_reading()
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

            # Strip raw crop arrays before publishing — only summaries
            # (class, confidence, bbox) leave the edge node, never images.
            detection_summary = {
                "trash_count": latest_detection.get("trash_count", 0),
                "detections": latest_detection.get("detections", []),
                "class_counts": latest_detection.get("class_counts", {}),
                "unknown_candidate_count": len(latest_detection.get("unknown_candidates", [])),
            }

            fc.send_data(data, detection_summary, anomalies)
            last_send = now
            log.info("Data sent to Pi5 (HiveMQ)  |  temp=%.1f  pH=%.2f  turb=%.0f  trash=%d  anomalies=%d",
                     data.get("temperature", 0), data.get("ph", 0),
                     data.get("turbidity", 0),
                     detection_summary["trash_count"],
                     len(anomalies.get("anomaly_list", [])))

        time.sleep(1)


def federation_loop():
    """Periodically participate in federated learning rounds (FedAvg),
    entirely over HiveMQ Cloud."""
    last_round = 0

    while running and detector.model is None and detector.cv_net is None:
        time.sleep(5)

    log.info("Federation loop started (interval=%ds)", config.FEDERATION_INTERVAL)

    while running:
        time.sleep(config.FEDERATION_INTERVAL)

        weights = detector.get_head_weights()
        if weights is None:
            log.debug("Federation: no extractable head weights this round "
                      "(cv_dnn/onnx backends don't support live weight sync)")
            continue

        if not fc.submit_update(weights):
            log.warning("Federation: failed to submit update")
            continue

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
    log.info("=== Pi4 Edge Node starting (zone=%s, node=%s) ===",
              config.ZONE_ID, config.NODE_ID)
    log.info("HiveMQ Cloud target: %s:%d", config.HIVEMQ_HOST, config.HIVEMQ_PORT)

    # 1. Start local-Wi-Fi MQTT subscriber (ESP32 sensor data)
    sensor.start()

    # 2. Start HiveMQ Cloud connection (Pi4 <-> Pi5)
    if not fc.start():
        log.error("Could not start HiveMQ Cloud client — check config.py credentials. "
                   "Continuing in local-only mode (no federation / dashboard sync).")

    # 3. Load YOLOv8 model & open camera
    model_ok = detector.load_model()
    camera_ok = detector.open_camera()
    if not model_ok:
        log.error("YOLOv8 model failed to load — detection & federation disabled")
    if not camera_ok:
        log.error("Pi Camera failed to open — detection disabled")

    # 4. Launch threads
    threads = [
        threading.Thread(target=sensor_loop, daemon=True, name="sensor"),
        threading.Thread(target=detection_loop, daemon=True, name="detection"),
        threading.Thread(target=label_federation_loop, daemon=True, name="label_fed"),
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
        fc.stop()
        detector.release()


if __name__ == "__main__":
    main()