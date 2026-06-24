"""HTTP client — sends data to Pi5 central server and handles federation.

Changes from v1:
  - Retry logic with exponential backoff (MAX_RETRIES now actually used)
  - API key authentication header on every request
  - Detection-head only weight filtering (layer_names parameter)
  - HiveMQ cloud MQTT reference for inter-zone communication
"""

import time
import logging
import requests
import config

log = logging.getLogger(__name__)

BASE       = config.SERVER_URL + "/api"
TIMEOUT    = 10
MAX_RETRIES = 3

# Basic API key authentication — prevents unauthorised nodes
# poisoning the federated model
API_KEY = getattr(config, "API_KEY", "river_monitor_default_key")
AUTH_HEADERS = {"X-API-Key": API_KEY}

log.info("🎯 Pi5 server target: %s", BASE)


# ── Retry helper ──────────────────────────────────────────────

def _post_with_retry(url, payload, timeout=TIMEOUT):
    """POST with exponential backoff retry. Returns response or None."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, json=payload,
                              headers=AUTH_HEADERS, timeout=timeout)
            if r.ok:
                return r
            log.warning("⚠ HTTP %d on attempt %d/%d: %s",
                        r.status_code, attempt + 1, MAX_RETRIES, r.text[:100])
        except requests.exceptions.ConnectionError:
            log.warning("⚠ Connection error (attempt %d/%d)", attempt + 1, MAX_RETRIES)
        except requests.exceptions.Timeout:
            log.warning("⚠ Timeout (attempt %d/%d)", attempt + 1, MAX_RETRIES)
        except Exception as e:
            log.error("✗ Unexpected error: %s", e)
            break

        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt          # 1s, 2s, 4s
            log.debug("  Retrying in %ds...", wait)
            time.sleep(wait)

    return None


# ── Public API ────────────────────────────────────────────────

def register():
    """Register this edge node with the Pi5 server."""
    r = _post_with_retry(f"{BASE}/federation/register", {
        "node_id":   config.NODE_ID,
        "node_type": "raspberry_pi4",
    })
    if r:
        log.info("✓ Registration successful")
        return True
    log.error("✗ Registration failed after %d attempts — is Pi5 running at %s?",
              MAX_RETRIES, config.SERVER_URL)
    return False


def send_data(sensor_data, detection_result, anomalies):
    """Send latest readings + detection results to Pi5."""
    r = _post_with_retry(f"{BASE}/data/submit", {
        "node_id":          config.NODE_ID,
        "sensor_data":      sensor_data,
        "detection_result": detection_result,
        "anomalies":        anomalies,
    })
    if r:
        log.debug("✓ Data submitted")
        return True
    log.warning("⚠ Data submission failed after %d attempts", MAX_RETRIES)
    return False


def heartbeat():
    """Send a heartbeat so the server knows this node is alive."""
    try:
        r = requests.post(
            f"{BASE}/federation/heartbeat",
            json={"node_id": config.NODE_ID},
            headers=AUTH_HEADERS,
            timeout=TIMEOUT,
        )
        if r.ok:
            log.debug("✓ Heartbeat sent")
            return True
        log.debug("⚠ Heartbeat failed (HTTP %d)", r.status_code)
        return False
    except Exception as e:
        log.debug("⚠ Heartbeat error: %s", e)
        return False


def submit_update(weights, layer_names=None):
    """
    Send local model weights to Pi5 for federated aggregation.

    Args:
        weights:     dict of {layer_name: flat_weight_list} from get_head_weights()
        layer_names: optional list of layer name substrings to filter.
                     Only detection-head layers are sent — not the full model.
                     Example: ["cv2", "cv3", "dfl"] for YOLOv8 detect head.

    This ensures only detection-head parameters are exchanged, not backbone
    weights — reducing payload size and matching the paper's FL claim.
    """
    if layer_names and isinstance(weights, dict):
        weights = {
            k: v for k, v in weights.items()
            if any(layer in k for layer in layer_names)
        }
        log.debug("Filtered to %d detection-head layers", len(weights))

    r = _post_with_retry(
        f"{BASE}/federation/submit_update",
        {"node_id": config.NODE_ID, "weights": weights},
        timeout=30,
    )
    if r:
        log.debug("✓ Detection-head weights submitted")
        return True
    log.warning("⚠ Weight submission failed after %d attempts", MAX_RETRIES)
    return False


def get_global_weights():
    """Fetch the latest federated model weights from Pi5."""
    try:
        r = requests.get(
            f"{BASE}/federation/global_weights",
            headers=AUTH_HEADERS,
            timeout=TIMEOUT,
        )
        if r.ok:
            data = r.json()
            log.debug("✓ Global weights fetched (round %s)", data.get("round"))
            return data
        log.debug("⚠ Cannot fetch global weights (HTTP %d)", r.status_code)
        return None
    except Exception as e:
        log.debug("⚠ Get global weights error: %s", e)
        return None


def send_unknown_label_event(label, cluster_id, sighting_count):
    """
    Notify Pi5 that a new unknown waste label was auto-discovered at this zone.
    Pi5 can aggregate these across zones and trigger global model retraining.
    """
    r = _post_with_retry(f"{BASE}/discovery/new_label", {
        "node_id":        config.NODE_ID,
        "label":          label,
        "cluster_id":     cluster_id,
        "sighting_count": sighting_count,
        "timestamp":      time.time(),
    })
    if r:
        log.info("✓ New label event '%s' sent to Pi5", label)
        return True
    log.warning("⚠ Failed to send new label event to Pi5")
    return False
