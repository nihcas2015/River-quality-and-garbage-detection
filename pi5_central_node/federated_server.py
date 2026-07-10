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
import numpy as np

log = logging.getLogger("federation")


class FederatedServer:
    """FedAvg aggregation + global label registry."""

    def __init__(self, min_nodes=1):
        self.min_nodes = min_nodes
        self.current_round = 0
        self.global_weights = None
        self.updates = {}        # {node_id: weights_array} — pending this round
        self.known_zones = set() # zone_ids seen so far, for broadcast fan-out
        self.confirmed_classes = []  # global label registry, ordered
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
        """Accept a newly-promoted label from any zone and add it to the
        confirmed global registry (idempotent). Returns True if the
        registry changed (i.e. worth republishing)."""
        with self.lock:
            if label in self.confirmed_classes:
                return False
            self.confirmed_classes.append(label)
            self.registry_version += 1
            log.warning("Label '%s' from zone=%s confirmed into global registry (v%d)",
                        label, zone_id, self.registry_version)
            return True

    def get_label_registry(self):
        return {"version": self.registry_version, "classes": list(self.confirmed_classes)}
