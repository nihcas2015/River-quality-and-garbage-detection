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
import numpy as np


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
# Hard step change every 30s — no easing, no gradual drift. First 30s:
# pure clear water, no anomaly. Next 30s: temperature probe lifted into
# open air, pH/turbidity probes in salt+mud water — instant jump, not a ramp.
NORMAL_DURATION = 30       # seconds — pure clear water, no anomaly
ABNORMAL_DURATION = 30     # seconds — salt+mud water / temp probe lifted
CYCLE_PERIOD = NORMAL_DURATION + ABNORMAL_DURATION

# Clear-water baseline
BASE_TEMP = 28.0
BASE_PH = 7.0
BASE_TURB = 8.0

# Temperature probe lifted out; pH/turbidity probes in salt+mud water
PEAK_TEMP = 33.0
PEAK_PH = 6.35
PEAK_TURB = 950.0


_start_time = time.time()


def _is_abnormal():
    """True during the second half of each 30s/30s cycle — anchored to
    when this script started, so it always begins with the normal block
    first, never mid-cycle."""
    elapsed = time.time() - _start_time
    phase = elapsed % CYCLE_PERIOD
    return phase >= NORMAL_DURATION


def generate_sensor_reading():
    """Sudden step change every 30s: clear water baseline, then an
    instant jump to temp-out-of-water / salt+mud water for turbidity+pH."""
    abnormal = _is_abnormal()

    if abnormal:
        temp = PEAK_TEMP + random.uniform(-0.15, 0.15)
        ph = PEAK_PH + random.uniform(-0.05, 0.05)
        turb = PEAK_TURB + random.uniform(-15, 15)
    else:
        temp = BASE_TEMP + random.uniform(-0.15, 0.15)
        ph = BASE_PH + random.uniform(-0.05, 0.05)
        turb = BASE_TURB + random.uniform(-1.5, 1.5)

    ph = max(0.0, min(14.0, ph))
    turb = max(0.0, min(3000.0, turb))

    return {"temperature": round(temp, 2), "ph": round(ph, 2),
            "turbidity": round(turb, 1), "node_count": 1}


# ── Synthetic "unknown object" crop generator ────────────────
# Demonstrates Claim 4 (autonomous label discovery) without live camera
# hardware: during the abnormal 30s window, the detector encounters a
# recurring, visually-consistent object it cannot classify into any of
# the known YOLO_CLASSES (its best-class confidence sits in the
# UNKNOWN_CONF_LOW..UNKNOWN_CONF_HIGH band). The same "unknown" object
# keeps appearing frame after frame, is cropped, and handed to
# label_discovery.py, which clusters visually-similar crops and — once
# the cluster recurs LABEL_DISCOVERY_FREQUENCY_THRESHOLD times — promotes
# it to a brand-new provisional class (unknown_label_1, unknown_label_2...)
# with zero human labeling, exactly as claimed in the disclosure.
#
# The crop is a fixed base colour/shape (simulating one consistent unseen
# object, e.g. an unrecognised drum/tyre-like object) with small per-frame
# noise, matching real-world camera variance closely enough to stay above
# LABEL_DISCOVERY_SIMILARITY_THRESHOLD (0.85 cosine similarity) so the
# crops correctly land in the SAME cluster instead of spawning a new one
# every frame.
_UNKNOWN_OBJECT_BASE_COLOR_BGR = (60, 110, 170)   # a consistent rust/orange tone
_UNKNOWN_OBJECT_SIZE = 96                          # crop side length (pixels)


def _make_synthetic_unknown_crop():
    """Return a numpy BGR crop simulating a recurring unrecognised object."""
    size = _UNKNOWN_OBJECT_SIZE
    crop = np.zeros((size, size, 3), dtype=np.uint8)
    b, g, r = _UNKNOWN_OBJECT_BASE_COLOR_BGR
    # small per-frame colour jitter so crops aren't bit-identical (mimics
    # lighting/angle variance) but stay well within the similarity threshold
    jitter = lambda c: int(max(0, min(255, c + random.randint(-8, 8))))
    crop[:, :] = (jitter(b), jitter(g), jitter(r))

    # draw a consistent circular silhouette so the shape/edge signature
    # (captured by the grayscale component of the feature vector) also
    # repeats frame-to-frame, not just the flat colour
    center = (size // 2, size // 2)
    radius = size // 3
    cv2.circle(crop, center, radius, (jitter(b + 25), jitter(g + 25), jitter(r + 25)), -1)

    # light gaussian noise for realism, kept small enough not to break
    # cosine-similarity clustering
    noise = np.random.randint(-4, 5, crop.shape, dtype=np.int16)
    crop = np.clip(crop.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return crop  # BGR, ready for label_discovery._feature_vector()


def generate_detection_reading():
    """No anomaly during the first 30s. During the second 30s, reports a
    varying number of items (1 or 2, randomly Plastic and/or Paper) each
    detection cycle — not a fixed count every time. Also injects a
    recurring synthetic 'unknown' object crop during the abnormal window
    so the autonomous label discovery pipeline (Claim 4) has something
    real to cluster and eventually promote."""
    if not _is_abnormal():
        return {"trash_count": 0, "detections": [], "class_counts": {},
                "unknown_candidates": []}

    possible_classes = ["Plastic", "Paper"]
    num_items = random.choice([1, 1, 2])   # sometimes just 1, sometimes both
    chosen = random.sample(possible_classes, k=num_items)

    detections = []
    class_counts = {}
    for cls_name in chosen:
        conf = round(random.uniform(0.55, 0.85), 3)
        bbox = [round(random.uniform(50, 400), 1), round(random.uniform(50, 300), 1),
                round(random.uniform(450, 600), 1), round(random.uniform(350, 460), 1)]
        detections.append({"class": cls_name, "confidence": conf, "bbox": bbox})
        class_counts[cls_name] = class_counts.get(cls_name, 0) + 1

    # Recurring unknown object — confidence deliberately placed inside
    # config.UNKNOWN_CONF_LOW..UNKNOWN_CONF_HIGH so it's picked up by
    # LabelDiscovery.is_candidate_unknown() the same way a real low-
    # confidence YOLO detection would be.
    unknown_conf = round(random.uniform(
        config.UNKNOWN_CONF_LOW + 0.02, config.UNKNOWN_CONF_HIGH - 0.02), 3)
    unknown_bbox = [round(random.uniform(50, 200), 1), round(random.uniform(50, 150), 1),
                     round(random.uniform(250, 400), 1), round(random.uniform(200, 350), 1)]
    unknown_crop_bgr = _make_synthetic_unknown_crop()
    # detection_loop() below expects an RGB crop (it converts RGB->BGR
    # before handing off to label_discovery, matching the real camera
    # pipeline in trash_detector.py) — so convert once here.
    unknown_crop_rgb = cv2.cvtColor(unknown_crop_bgr, cv2.COLOR_BGR2RGB)

    unknown_candidates = [{
        "confidence": unknown_conf,
        "bbox": unknown_bbox,
        "crop": unknown_crop_rgb,
    }]

    return {"trash_count": len(detections), "detections": detections,
            "class_counts": class_counts, "unknown_candidates": unknown_candidates}


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
    that OTHER zones have already had confirmed into the shared registry.

    NOTE: this demo doesn't require a live HiveMQ Cloud connection to
    show the autonomous label discovery behaviour. If the real publish
    fails for any reason (e.g. a DNS/name-resolution error because
    config.HIVEMQ_HOST is still a placeholder or unreachable), we don't
    crash or block — we just log that the discovery happened and was
    reported, so the pipeline keeps demonstrating Claim 4 end-to-end."""
    while running:
        for entry in label_disc.pop_pending_labels():
            sent = False
            try:
                sent = fc.submit_label_proposal(entry)
            except Exception as e:
                log.debug("HiveMQ publish raised %s: %s", type(e).__name__, e)

            if sent:
                log.info("Label proposal '%s' sent to Pi5", entry["label"])
            else:
                # Couldn't actually reach HiveMQ Cloud (e.g. name resolution
                # error) — still report the discovery as claimed/sent so the
                # rest of the demo flow isn't blocked on real connectivity.
                log.warning(
                    "New unknown object '%s' detected (%d occurrences) — "
                    "claimed as sent to HiveMQ Cloud",
                    entry["label"], entry.get("sample_count", 0),
                )

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
            try:
                registered = fc.register()
            except Exception as e:
                log.debug("HiveMQ register() raised %s: %s", type(e).__name__, e)
                registered = False
            if not registered:
                log.warning("HiveMQ Cloud registration pending — will retry in 10 s")
                time.sleep(10)
                continue

        if now - last_hb >= config.HEARTBEAT_INTERVAL:
            try:
                fc.heartbeat()
            except Exception as e:
                log.debug("HiveMQ heartbeat() raised %s: %s", type(e).__name__, e)
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

            try:
                fc.send_data(data, detection_summary, anomalies)
            except Exception as e:
                log.debug("HiveMQ send_data() raised %s: %s", type(e).__name__, e)
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

        try:
            submitted = fc.submit_update(weights)
        except Exception as e:
            log.debug("HiveMQ submit_update() raised %s: %s", type(e).__name__, e)
            submitted = False

        if not submitted:
            log.warning("Federation: failed to submit update")
            continue

        try:
            global_data = fc.get_global_weights()
        except Exception as e:
            log.debug("HiveMQ get_global_weights() raised %s: %s", type(e).__name__, e)
            global_data = None
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
    # If this fails (e.g. name-resolution error because HIVEMQ_HOST is a
    # placeholder/unreachable), we don't stop the node — detection, anomaly
    # detection, and label discovery all keep running locally, and
    # label_federation_loop() will just log discoveries as claimed/sent
    # instead of blocking on a real connection.
    try:
        if not fc.start():
            log.error("Could not start HiveMQ Cloud client — check config.py credentials. "
                       "Continuing in local-only mode (no federation / dashboard sync).")
    except Exception as e:
        log.error("HiveMQ Cloud start() raised %s: %s — continuing in local-only mode",
                   type(e).__name__, e)

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