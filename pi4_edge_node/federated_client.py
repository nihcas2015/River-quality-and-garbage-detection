"""HTTP client — sends data to Pi5 central server and handles federation."""

import logging
import requests
import config

log = logging.getLogger(__name__)

BASE = config.SERVER_URL + "/api"
TIMEOUT = 10

log.info("Pi5 server target: %s", BASE)


def register():
    """Register this edge node with the Pi5 server."""
    url = f"{BASE}/federation/register"
    try:
        r = requests.post(url, json={
            "node_id": config.NODE_ID,
            "node_type": "raspberry_pi4",
        }, timeout=TIMEOUT)
        log.info("Register → %s  status=%s  body=%s", url, r.status_code, r.text[:200])
        return r.ok
    except Exception as e:
        log.error("Register → %s  FAILED: %s", url, e)
        return False


def send_data(sensor_data, detection_result, anomalies):
    """Send latest readings + detection results to Pi5."""
    url = f"{BASE}/data/submit"
    try:
        payload = {
            "node_id": config.NODE_ID,
            "sensor_data": sensor_data,
            "detection_result": detection_result,
            "anomalies": anomalies,
        }
        r = requests.post(url, json=payload, timeout=TIMEOUT)
        log.info("Send data → %s  status=%s", url, r.status_code)
        return r.ok
    except Exception as e:
        log.error("Send data → %s  FAILED: %s", url, e)
        return False


def heartbeat():
    """Send a heartbeat so the server knows we are alive."""
    try:
        r = requests.post(f"{BASE}/federation/heartbeat", json={
            "node_id": config.NODE_ID,
        }, timeout=TIMEOUT)
        return r.ok
    except Exception as e:
        log.debug("Heartbeat FAILED: %s", e)
        return False


def get_global_weights():
    """Fetch the latest federated model weights from Pi5."""
    try:
        r = requests.get(f"{BASE}/federation/global_weights", timeout=TIMEOUT)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None
