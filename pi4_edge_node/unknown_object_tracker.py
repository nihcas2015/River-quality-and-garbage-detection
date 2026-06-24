"""
Autonomous Unknown Object Discovery Module.

When YOLO detects something but confidence is below UNKNOWN_CONFIDENCE_THRESHOLD
for ALL known classes, the object is flagged as unknown. Once enough sightings
of visually similar unknowns accumulate (UNKNOWN_CLUSTER_THRESHOLD), a new label
is automatically created (new_object_1, new_object_2, ...) and the best image
is published to the central dashboard via HiveMQ MQTT.

This enables the system to autonomously discover new waste categories without
any human labelling — the core novelty of this architecture.
"""

import os
import time
import json
import logging
import ssl
import base64
import hashlib
from collections import defaultdict

import cv2
import numpy as np
import paho.mqtt.client as mqtt
import config

log = logging.getLogger(__name__)


class UnknownObjectTracker:
    """
    Tracks low-confidence detections, clusters similar ones,
    and auto-creates new labels when a cluster exceeds threshold.

    Novelty claim: autonomous waste category discovery without human annotation,
    with federated label propagation via MQTT to all zones.
    """

    def __init__(self):
        # {cluster_id: {"count": int, "best_frame": ndarray, "best_conf": float,
        #               "first_seen": timestamp, "label": str}}
        self.clusters      = {}
        self.next_label_id = 1
        self.total_unknown = 0

        # MQTT client for publishing unknown object alerts to dashboard
        self.mqtt_client   = None
        self._mqtt_ready   = False

        # Local storage for unknown images
        os.makedirs(config.UNKNOWN_IMAGES_DIR, exist_ok=True)

        self._init_mqtt()
        log.info("UnknownObjectTracker initialised "
                 "(conf_threshold=%.2f, cluster_threshold=%d)",
                 config.UNKNOWN_CONFIDENCE_THRESHOLD,
                 config.UNKNOWN_CLUSTER_THRESHOLD)

    # ── MQTT setup ────────────────────────────────────────────

    def _init_mqtt(self):
        """Connect a dedicated MQTT client for publishing unknown object events."""
        try:
            self.mqtt_client = mqtt.Client(
                client_id=f"{config.NODE_ID}_unknown_tracker",
                protocol=mqtt.MQTTv311,
            )
            self.mqtt_client.username_pw_set(
                config.MQTT_USERNAME, config.MQTT_PASSWORD)
            if config.MQTT_USE_TLS:
                self.mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS)

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.connect(
                config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            log.warning("⚠ UnknownTracker MQTT init failed: %s", e)

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._mqtt_ready = True
            log.info("✓ UnknownTracker MQTT connected to HiveMQ")
        else:
            log.warning("⚠ UnknownTracker MQTT connect failed rc=%d", rc)

    # ── Core logic ────────────────────────────────────────────

    def process_frame(self, frame, raw_scores):
        """
        Call after every YOLO inference pass.

        Args:
            frame:      numpy array (H, W, 3) — the captured camera frame
            raw_scores: list of floats — max confidence score per detection
                        Pass an empty list [] if no detections at all.

        Returns:
            dict with keys:
                unknown_detected  (bool)
                new_label_created (bool)
                new_label         (str or None)
                total_unknown     (int)
        """
        result = {
            "unknown_detected":  False,
            "new_label_created": False,
            "new_label":         None,
            "total_unknown":     self.total_unknown,
        }

        # Check if any detection has all scores below threshold
        unknown_in_frame = False
        if raw_scores:
            for score in raw_scores:
                if score < config.UNKNOWN_CONFIDENCE_THRESHOLD:
                    unknown_in_frame = True
                    break
        else:
            # No detections at all but something may be in frame
            # Only flag if we actually had a detection attempt
            pass

        if not unknown_in_frame:
            return result

        self.total_unknown += 1
        result["unknown_detected"] = True

        # ── Cluster by simple visual hash ─────────────────────
        cluster_id = self._compute_visual_hash(frame)

        if cluster_id not in self.clusters:
            self.clusters[cluster_id] = {
                "count":      0,
                "best_frame": None,
                "best_score": 0.0,
                "first_seen": time.time(),
                "label":      None,
            }
            log.debug("New unknown cluster: %s", cluster_id[:8])

        cluster = self.clusters[cluster_id]
        cluster["count"] += 1

        # Keep the clearest frame (highest overall brightness = best lit)
        frame_quality = float(np.mean(frame))
        if frame_quality > cluster.get("best_score", 0):
            cluster["best_frame"] = frame.copy()
            cluster["best_score"] = frame_quality

        log.debug("Unknown cluster %s: sightings=%d/%d",
                  cluster_id[:8], cluster["count"],
                  config.UNKNOWN_CLUSTER_THRESHOLD)

        # ── Auto-label when threshold reached ─────────────────
        if (cluster["count"] >= config.UNKNOWN_CLUSTER_THRESHOLD
                and cluster["label"] is None):

            new_label = f"new_object_{self.next_label_id}"
            self.next_label_id += 1
            cluster["label"] = new_label

            log.info("🆕 New waste category discovered: %s "
                     "(cluster=%s, sightings=%d)",
                     new_label, cluster_id[:8], cluster["count"])

            # Save best image locally
            img_path = self._save_unknown_image(
                cluster["best_frame"], new_label, cluster_id)

            # Publish to HiveMQ → central dashboard
            self._publish_new_label(new_label, cluster_id, img_path,
                                    cluster["count"], cluster["first_seen"])

            result["new_label_created"] = True
            result["new_label"]         = new_label

        result["total_unknown"] = self.total_unknown
        return result

    # ── Helpers ───────────────────────────────────────────────

    def _compute_visual_hash(self, frame):
        """
        Compute a simple perceptual hash to group visually similar frames.
        Resize to 16x16 greyscale, threshold, and hash the bit pattern.
        Similar objects produce the same or nearby hash.
        """
        small   = cv2.resize(frame, (16, 16))
        grey    = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        mean    = grey.mean()
        bits    = (grey > mean).flatten().tobytes()
        return hashlib.md5(bits).hexdigest()

    def _save_unknown_image(self, frame, label, cluster_id):
        """Save the best frame for a new unknown label to disk."""
        filename  = f"{label}_{cluster_id[:8]}_{int(time.time())}.jpg"
        img_path  = os.path.join(config.UNKNOWN_IMAGES_DIR, filename)
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imwrite(img_path, bgr_frame)
        log.info("💾 Unknown object image saved: %s", img_path)
        return img_path

    def _publish_new_label(self, label, cluster_id, img_path,
                           sighting_count, first_seen):
        """
        Publish new unknown label event to HiveMQ cloud MQTT.
        Central dashboard subscribes to river/unknown_objects and displays
        the image for optional human verification.
        """
        if not self._mqtt_ready or self.mqtt_client is None:
            log.warning("⚠ Cannot publish unknown label — MQTT not ready")
            return

        # Encode image as base64 for MQTT payload
        img_b64 = ""
        try:
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            log.warning("⚠ Could not encode image: %s", e)

        payload = {
            "event":         "new_unknown_label",
            "label":         label,
            "node_id":       config.NODE_ID,
            "cluster_id":    cluster_id,
            "sighting_count": sighting_count,
            "first_seen":    first_seen,
            "timestamp":     time.time(),
            "image_b64":     img_b64,        # best image for dashboard display
        }

        try:
            self.mqtt_client.publish(
                config.MQTT_TOPIC_UNKNOWN,
                json.dumps(payload),
                qos=1,          # at-least-once delivery
                retain=True,    # new subscribers see the latest unknown labels
            )
            log.info("📡 Published new label '%s' to HiveMQ dashboard topic", label)
        except Exception as e:
            log.error("✗ Failed to publish unknown label: %s", e)

    def get_summary(self):
        """Return summary of unknown object tracking for dashboard."""
        return {
            "total_unknown_sightings": self.total_unknown,
            "active_clusters":         len(self.clusters),
            "auto_labels_created":     self.next_label_id - 1,
            "labels": [
                {"label": v["label"], "sightings": v["count"],
                 "first_seen": v["first_seen"]}
                for v in self.clusters.values()
                if v["label"] is not None
            ],
        }

    def stop(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
