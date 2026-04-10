"""HTTP client — sends data to Pi5 central server and handles federation."""

import logging
import requests
import config

log = logging.getLogger(__name__)

BASE = config.SERVER_URL + "/api"
TIMEOUT = 10
MAX_RETRIES = 3

log.info("🎯 Pi5 server target: %s", BASE)


def register():
    """Register this edge node with the Pi5 server."""
    url = f"{BASE}/federation/register"
    try:
        r = requests.post(url, json={
            "node_id": config.NODE_ID,
            "node_type": "raspberry_pi4",
        }, timeout=TIMEOUT)
        
        if r.ok:
            log.info("✓ Registration successful: %s", r.text[:200])
            return True
        else:
            log.warning("⚠ Registration failed (HTTP %d): %s", 
                       r.status_code, r.text[:200])
            return False
    except requests.exceptions.ConnectionError as e:
        log.error("✗ Cannot reach Pi5 server: %s", e)
        log.error("  → Check if Pi5 is running on %s:%d", 
                 config.PI5_IP, config.PI5_PORT)
        return False
    except requests.exceptions.Timeout:
        log.error("✗ Registration timeout (Pi5 not responding)")
        return False
    except Exception as e:
        log.error("✗ Registration error: %s", e)
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
        
        if r.ok:
            log.debug("✓ Data submitted (HTTP %d)", r.status_code)
            return True
        else:
            log.warning("⚠ Data submission failed (HTTP %d): %s",
                       r.status_code, r.text[:200])
            return False
    except requests.exceptions.ConnectionError:
        log.error("✗ Cannot reach Pi5 (connection error)")
        return False
    except requests.exceptions.Timeout:
        log.warning("⚠ Data submission timeout")
        return False
    except Exception as e:
        log.error("✗ Send data error: %s", e)
        return False


def heartbeat():
    """Send a heartbeat so the server knows we are alive."""
    try:
        r = requests.post(f"{BASE}/federation/heartbeat", json={
            "node_id": config.NODE_ID,
        }, timeout=TIMEOUT)
        if r.ok:
            log.debug("✓ Heartbeat sent")
            return True
        else:
            log.debug("⚠ Heartbeat failed (HTTP %d)", r.status_code)
            return False
    except requests.exceptions.Timeout:
        log.debug("⚠ Heartbeat timeout")
        return False
    except Exception as e:
        log.debug("⚠ Heartbeat error: %s", e)
        return False


def submit_update(weights):
    """Send local model weights to Pi5 for federated aggregation."""
    url = f"{BASE}/federation/submit_update"
    try:
        r = requests.post(url, json={
            "node_id": config.NODE_ID,
            "weights": weights,
        }, timeout=30)
        
        if r.ok:
            log.debug("✓ Model weights submitted (HTTP %d)", r.status_code)
            return True
        else:
            log.warning("⚠ Weight submission failed (HTTP %d)", r.status_code)
            return False
    except requests.exceptions.Timeout:
        log.warning("⚠ Weight submission timeout")
        return False
    except Exception as e:
        log.error("✗ Submit update error: %s", e)
        return False


def get_global_weights():
    """Fetch the latest federated model weights from Pi5."""
    url = f"{BASE}/federation/global_weights"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.ok:
            data = r.json()
            log.debug("✓ Global weights fetched (round %s)", data.get("round"))
            return data
        else:
            log.debug("⚠ Cannot fetch global weights (HTTP %d)", r.status_code)
            return None
    except requests.exceptions.Timeout:
        log.debug("⚠ Global weights timeout")
        return None
    except Exception as e:
        log.debug("⚠ Get global weights error: %s", e)
        return None
