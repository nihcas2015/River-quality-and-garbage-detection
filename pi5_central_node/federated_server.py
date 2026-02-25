"""
Federated Learning Server (FedAvg) — runs alongside server.py on Pi5.

Collects model updates from Pi4 edge nodes and averages them
into a global model. Lightweight implementation for YOLOv8 weights.
"""

import logging
import threading
import time
import numpy as np

log = logging.getLogger("federation")


class FederatedServer:
    """Simple FedAvg aggregation for edge-node model updates."""

    def __init__(self, min_nodes=1, round_timeout=300):
        self.min_nodes = min_nodes
        self.round_timeout = round_timeout
        self.current_round = 0
        self.global_weights = None
        self.updates = {}       # {node_id: weights_array}
        self.lock = threading.Lock()

    def receive_update(self, node_id, weights):
        """Store a local model update from an edge node."""
        with self.lock:
            self.updates[node_id] = np.array(weights, dtype=np.float32)
            log.info("Update from %s (round %d), %d/%d received",
                     node_id, self.current_round,
                     len(self.updates), self.min_nodes)

        if len(self.updates) >= self.min_nodes:
            self.aggregate()

    def aggregate(self):
        """Average all received weight updates (FedAvg)."""
        with self.lock:
            if not self.updates:
                return

            arrays = list(self.updates.values())
            self.global_weights = np.mean(arrays, axis=0).tolist()
            self.current_round += 1
            self.updates.clear()

            log.info("Round %d aggregated (%d nodes)",
                     self.current_round, len(arrays))

    def get_global_weights(self):
        return {"round": self.current_round, "weights": self.global_weights}
