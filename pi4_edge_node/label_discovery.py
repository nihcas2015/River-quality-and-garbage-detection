"""
Autonomous Waste Label Discovery Module
────────────────────────────────────────
Implements the "open-set" mechanism described in the patent disclosure:

  1. Any YOLO detection whose best class-confidence falls below the known
     classification threshold (but above a noise floor) is treated as a
     candidate UNKNOWN object.
  2. Crops of these unknown objects are buffered and grouped by visual
     similarity (lightweight colour-histogram + downsampled-pixel feature
     vector — cheap enough to run continuously on a Pi4 with no GPU).
  3. When a cluster's occurrence count crosses a configurable frequency
     threshold, the module "promotes" it: it mints a new provisional label
     (unknown_label_1, unknown_label_2, ...), saves the clustered crops to
     disk as training samples, and appends the label to config.YOLO_CLASSES
     so the running detector can start reporting it immediately.
  4. Promoted labels + their sample crops are queued for the next federated
     learning round (fed to Pi5 via HiveMQ so every zone's model benefits,
     per patent Claim 4).

No manual re-labeling is required — this is the "no human intervention"
novelty claimed in the disclosure. No extra heavy dependencies (no sklearn/
torch) so it stays light enough for Pi4's ARM Cortex-A72.
"""

import os
import time
import logging
import numpy as np
import cv2
import config

log = logging.getLogger(__name__)


def _feature_vector(crop_bgr, size=None):
    """Cheap, deterministic visual signature for a cropped detection.

    Combines a downsampled grayscale pixel vector with a coarse HSV colour
    histogram. This is NOT a learned embedding — it's intentionally simple
    so it runs in milliseconds on a Pi4 with zero extra dependencies. Good
    enough to separate visually distinct 'unknown' object types (e.g. a
    tyre vs. a plastic drum vs. a dead fish) into different clusters.
    """
    size = size or config.LABEL_DISCOVERY_CROP_SIZE
    resized = cv2.resize(crop_bgr, (size, size), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32).flatten()
    gray /= (np.linalg.norm(gray) + 1e-8)

    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
    hist = hist.flatten().astype(np.float32)
    hist /= (np.linalg.norm(hist) + 1e-8)

    return np.concatenate([gray * 0.5, hist * 0.5])


def _cosine_sim(a, b):
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
    return float(np.dot(a, b) / denom)


class _UnknownCluster:
    """A running cluster of visually-similar unknown-object crops."""

    def __init__(self, cluster_id, feature, crop):
        self.cluster_id = cluster_id
        self.centroid = feature.copy()
        self.count = 1
        self.sample_crops = [crop]
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.promoted = False
        self.promoted_label = None

    def add(self, feature, crop, max_samples=20):
        # incremental centroid update (running mean)
        self.count += 1
        self.centroid = self.centroid + (feature - self.centroid) / self.count
        self.last_seen = time.time()
        if len(self.sample_crops) < max_samples:
            self.sample_crops.append(crop)


class LabelDiscovery:
    """Buffers unknown detections, clusters them, and promotes new labels."""

    def __init__(self):
        self.clusters = []          # list[_UnknownCluster]
        self.next_cluster_id = 1
        self.promoted_count = 0
        self.pending_federation_labels = []   # labels not yet sent to Pi5
        os.makedirs(config.LABEL_DISCOVERY_SAMPLES_DIR, exist_ok=True)
        log.info(
            "LabelDiscovery initialised (sim_thresh=%.2f, freq_thresh=%d)",
            config.LABEL_DISCOVERY_SIMILARITY_THRESHOLD,
            config.LABEL_DISCOVERY_FREQUENCY_THRESHOLD,
        )

    # ── ingestion ─────────────────────────────────────────────

    def is_candidate_unknown(self, confidence):
        """True if a detection's confidence sits in the 'unknown' band —
        not confident enough to be a known class, not low enough to be
        pure background/noise."""
        return config.UNKNOWN_CONF_LOW <= confidence < config.UNKNOWN_CONF_HIGH

    def observe(self, crop_bgr, confidence, bbox=None):
        """Feed one candidate-unknown crop into the clustering pipeline.
        Returns a newly-promoted label name (str) if this observation
        pushed a cluster over the promotion threshold, else None.
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return None

        feature = _feature_vector(crop_bgr)

        # Find best matching existing cluster
        best_cluster, best_sim = None, -1.0
        for c in self.clusters:
            sim = _cosine_sim(feature, c.centroid)
            if sim > best_sim:
                best_sim, best_cluster = sim, c

        if best_cluster is not None and best_sim >= config.LABEL_DISCOVERY_SIMILARITY_THRESHOLD:
            best_cluster.add(feature, crop_bgr)
            cluster = best_cluster
        else:
            cluster = _UnknownCluster(self.next_cluster_id, feature, crop_bgr)
            self.next_cluster_id += 1
            self.clusters.append(cluster)
            self._enforce_buffer_cap()

        log.debug(
            "Unknown obs -> cluster #%d (count=%d, conf=%.2f, best_sim=%.2f)",
            cluster.cluster_id, cluster.count, confidence, best_sim,
        )

        if (not cluster.promoted
                and cluster.count >= config.LABEL_DISCOVERY_FREQUENCY_THRESHOLD):
            return self._promote(cluster)
        return None

    # ── promotion ─────────────────────────────────────────────

    def _promote(self, cluster):
        """Mint a new provisional label for a cluster that has recurred
        often enough, save its sample crops, and register it locally."""
        self.promoted_count += 1
        label = f"{config.LABEL_DISCOVERY_PREFIX}{self.promoted_count}"
        cluster.promoted = True
        cluster.promoted_label = label

        # Persist sample crops so they can be added to the training set
        label_dir = os.path.join(config.LABEL_DISCOVERY_SAMPLES_DIR, label)
        os.makedirs(label_dir, exist_ok=True)
        for i, crop in enumerate(cluster.sample_crops):
            try:
                cv2.imwrite(os.path.join(label_dir, f"sample_{i:03d}.jpg"), crop)
            except Exception as e:
                log.warning("Could not save sample crop for %s: %s", label, e)

        # Make the new class visible to the running detector immediately
        if label not in config.YOLO_CLASSES:
            config.YOLO_CLASSES.append(label)

        # Queue for the next federated round so ALL zones learn it too
        self.pending_federation_labels.append({
            "label": label,
            "cluster_id": cluster.cluster_id,
            "sample_count": len(cluster.sample_crops),
            "node_id": config.NODE_ID,
            "discovered_at": time.time(),
        })

        log.warning(
            "AUTONOMOUS LABEL DISCOVERY: cluster #%d promoted to new class '%s' "
            "(%d occurrences, %d samples saved to %s)",
            cluster.cluster_id, label, cluster.count,
            len(cluster.sample_crops), label_dir,
        )
        return label

    def _enforce_buffer_cap(self):
        """Drop the coldest (least-recently-seen, unpromoted) cluster if
        we exceed the memory bound — keeps this safe for a Pi4."""
        total_crops = sum(len(c.sample_crops) for c in self.clusters)
        if total_crops <= config.LABEL_DISCOVERY_MAX_BUFFER:
            return
        candidates = [c for c in self.clusters if not c.promoted]
        if not candidates:
            return
        oldest = min(candidates, key=lambda c: c.last_seen)
        self.clusters.remove(oldest)
        log.debug("Evicted cold unknown-cluster #%d to respect buffer cap", oldest.cluster_id)

    # ── federation hand-off ───────────────────────────────────

    def pop_pending_labels(self):
        """Return and clear labels discovered since the last federation
        round, so main_edge.py's federation_loop can ship them to Pi5."""
        pending, self.pending_federation_labels = self.pending_federation_labels, []
        return pending

    def status(self):
        return {
            "active_clusters": len(self.clusters),
            "promoted_labels": self.promoted_count,
            "known_classes": len(config.YOLO_CLASSES),
        }
