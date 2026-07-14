"""
Federated Learning + Label Registry Server (Pi5).

- FedAvg: collects YOLOv8 detection-head weight updates from zones,
  averages them, and hands back a payload {"round": int, "weights": [...]}
  that server.py publishes to each zone's river/{zone_id}/federation/global
  topic (edge nodes subscribe to their own zone's topic — see
  federated_client.py on the edge side).
- Label registry: accepts autonomously-discovered "unknown_label_N"
  proposals from any zone and republishes the confirmed, deduplicated
  list to river/label_registry/global so every zone adopts labels
  discovered elsewhere (Claim 4).
"""

import logging
import threading
from datetime import datetime
import numpy as np

log = logging.getLogger("federation")


def _now_iso():
    return datetime.utcnow().isoformat() + "Z"


class FederatedServer:
    """FedAvg aggregation + global label registry."""

    def __init__(self, min_nodes=1):
        self.min_nodes = min_nodes
        self.current_round = 0
        self.global_weights = None
        self.updates = {}        # {node_id: weights_array} — pending this round
        self.known_zones = set() # zone_ids seen so far, for broadcast fan-out
        self.confirmed_classes = []  # global label registry, ordered (label strings)
        self.label_meta = {}         # {label: {sighting_count, zones:set, first_seen}}
        self.registry_version = 0
        self.lock = threading.Lock()

    # ── FedAvg ────────────────────────────────────────────────

    def receive_update(self, node_id, zone_id, weights):
        """Store a local model update. Returns True if this update
        triggered a new aggregated round."""
        with self.lock:
            self.updates[node_id] = np.array(weights, dtype=np.float32)
            if zone_id:
                self.known_zones.add(zone_id)
            log.info("Update from %s/%s (round %d), %d/%d received",
                      zone_id, node_id, self.current_round,
                      len(self.updates), self.min_nodes)
            ready = len(self.updates) >= self.min_nodes

        if ready:
            return self._aggregate()
        return False

    def _aggregate(self):
        with self.lock:
            if not self.updates:
                return False
            arrays = list(self.updates.values())
            self.global_weights = np.mean(arrays, axis=0).tolist()
            self.current_round += 1
            n = len(arrays)
            self.updates.clear()
        log.info("Round %d aggregated (%d node updates)", self.current_round, n)
        return True

    def get_global_weights(self):
        return {"round": self.current_round, "weights": self.global_weights}

    # ── Label registry ───────────────────────────────────────

    def register_label_proposal(self, zone_id, label, **meta):
        """Accept a newly-promoted label from any zone and add/update it in the
        confirmed global registry (idempotent on first-confirm). Returns True
        only when a brand-new label is added (i.e. worth republishing the
        registry to all zones). Repeat sightings of an already-confirmed
        label still update metadata but don't trigger a full re-broadcast."""
        with self.lock:
            is_new = label not in self.confirmed_classes
            if is_new:
                self.confirmed_classes.append(label)
                self.registry_version += 1

            entry = self.label_meta.setdefault(label, {
                "sighting_count": 0,
                "zones": set(),
                "first_seen": meta.get("discovered_at") or _now_iso(),
            })
            entry["sighting_count"] += int(meta.get("sample_count") or 1)
            if zone_id:
                entry["zones"].add(zone_id)

            if is_new:
                log.warning("Label '%s' from zone=%s confirmed into global registry (v%d)",
                            label, zone_id, self.registry_version)
            return is_new

    def get_label_registry(self):
        detail = [
            {
                "label": label,
                "sighting_count": self.label_meta.get(label, {}).get("sighting_count", 0),
                "zones": sorted(self.label_meta.get(label, {}).get("zones", set())),
                "first_seen": self.label_meta.get(label, {}).get("first_seen"),
            }
            for label in self.confirmed_classes
        ]
        return {
            "version": self.registry_version,
            "classes": list(self.confirmed_classes),
            "classes_detail": detail,
        }

    def get_unknown_objects_summary(self):
        total = sum(v.get("sighting_count", 0) for v in self.label_meta.values())
        return {
            "total_sightings": total,
            "labels": self.get_label_registry()["classes_detail"],
        }