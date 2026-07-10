"""
HiveMQ Cloud MQTT client — Pi4 (edge) <-> Pi5 (central) link.

Per the patent disclosure (Claim 3), this is the ONLY channel between the
edge node and the central aggregation server. It is NOT the same MQTT
broker used for ESP32 <-> Pi4 (that stays on local Wi-Fi via a Mosquitto
broker running on this Pi4 — see sensor_reader.py). This client instead
connects over TLS to HiveMQ Cloud, which routes messages over the public
internet, so a node can be placed anywhere along the river without being
on the same LAN as the Pi5 central node.

Replaces the previous HTTP/requests implementation, which required
`config.SERVER_URL` (a local Pi5 IP) — that setting does not exist in this
codebase's config.py and directly contradicts the "no local network
proximity" novelty claimed in the disclosure.

Topics used (all already defined in config.py):
    HIVEMQ_TOPIC_REGISTER        -> Pi4 announces itself to Pi5
    HIVEMQ_TOPIC_HEARTBEAT       -> Pi4 liveness ping
    HIVEMQ_TOPIC_DATA_SUBMIT     -> sensor + detection + anomaly payloads
    HIVEMQ_TOPIC_FED_SUBMIT      -> local YOLOv8 detection-head weights
    HIVEMQ_TOPIC_FED_GLOBAL      -> Pi5 -> Pi4 aggregated global weights (subscribe)
    HIVEMQ_TOPIC_LABEL_PROPOSAL  -> newly discovered "unknown_label_N" proposals
    HIVEMQ_TOPIC_LABEL_REGISTRY  -> Pi5 -> all zones, confirmed shared label list (subscribe)
"""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt
import config

log = logging.getLogger(__name__)


class HiveMQClient:
    """Wraps a single persistent MQTT/TLS connection to HiveMQ Cloud."""

    def __init__(self):
        self.client = mqtt.Client(client_id=config.HIVEMQ_CLIENT_ID, clean_session=True)
        self.client.username_pw_set(config.HIVEMQ_USERNAME, config.HIVEMQ_PASSWORD)
        if config.HIVEMQ_USE_TLS:
            self.client.tls_set()   # uses system CA certs; HiveMQ Cloud uses public CAs
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self.connected = False
        self._lock = threading.Lock()
        self.latest_global_weights = None   # {"round": int, "weights": [...]}
        self.latest_label_registry = None   # {"classes": [...], "version": int}

    # ── connection lifecycle ─────────────────────────────────

    def start(self):
        if "xxxxxxxxxxxx" in config.HIVEMQ_HOST or config.HIVEMQ_PASSWORD == "CHANGE_ME":
            log.error(
                "HiveMQ Cloud credentials are still placeholders! "
                "Set HIVEMQ_HOST / HIVEMQ_USERNAME / HIVEMQ_PASSWORD in config.py "
                "(create a cluster + device credentials at https://console.hivemq.cloud)."
            )
            return False
        try:
            self.client.connect(config.HIVEMQ_HOST, config.HIVEMQ_PORT,
                                 keepalive=config.HIVEMQ_KEEPALIVE)
            self.client.loop_start()
            return True
        except Exception as e:
            log.error("HiveMQ Cloud connect failed: %s", e)
            return False

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe(config.HIVEMQ_TOPIC_FED_GLOBAL, qos=config.HIVEMQ_QOS)
            client.subscribe(config.HIVEMQ_TOPIC_LABEL_REGISTRY, qos=config.HIVEMQ_QOS)
            log.info("Connected to HiveMQ Cloud (%s) — subscribed to global model + label registry",
                      config.HIVEMQ_HOST)
        else:
            log.error("HiveMQ Cloud connect rc=%d (check credentials/cluster URL)", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            log.warning("Unexpected HiveMQ Cloud disconnect (rc=%d) — paho will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            log.warning("Bad JSON on %s", msg.topic)
            return

        with self._lock:
            if msg.topic == config.HIVEMQ_TOPIC_FED_GLOBAL:
                self.latest_global_weights = payload
                log.info("Received global model round=%s from Pi5", payload.get("round"))
            elif msg.topic == config.HIVEMQ_TOPIC_LABEL_REGISTRY:
                self.latest_label_registry = payload
                log.info("Received global label registry (v%s, %d classes)",
                          payload.get("version"), len(payload.get("classes", [])))

    # ── publish helpers ──────────────────────────────────────

    def _publish(self, topic, payload_dict, qos=None):
        if not self.connected:
            log.debug("Publish skipped — not connected to HiveMQ Cloud (topic=%s)", topic)
            return False
        try:
            body = json.dumps(payload_dict)
            if len(body.encode()) > config.HIVEMQ_MAX_PAYLOAD_BYTES:
                log.error("Payload for %s exceeds max size, dropping", topic)
                return False
            info = self.client.publish(topic, body, qos=qos or config.HIVEMQ_QOS)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            log.error("Publish to %s failed: %s", topic, e)
            return False


_hive = HiveMQClient()


def start():
    """Call once at startup, from main_edge.py."""
    return _hive.start()


def stop():
    _hive.stop()


def register():
    """Announce this edge node to Pi5 (equivalent of the old HTTP register())."""
    if not _hive.connected:
        _hive.start()
        time.sleep(1)
    return _hive._publish(config.HIVEMQ_TOPIC_REGISTER, {
        "node_id": config.NODE_ID,
        "zone_id": config.ZONE_ID,
        "node_type": "raspberry_pi4",
        "ts": time.time(),
    })


def heartbeat():
    return _hive._publish(config.HIVEMQ_TOPIC_HEARTBEAT, {
        "node_id": config.NODE_ID,
        "ts": time.time(),
    })


def send_data(sensor_data, detection_result, anomalies):
    """Publish sensor + detection + anomaly summary — no raw images/readings
    beyond this zone-level summary, per the privacy-preserving design."""
    return _hive._publish(config.HIVEMQ_TOPIC_DATA_SUBMIT, {
        "node_id": config.NODE_ID,
        "zone_id": config.ZONE_ID,
        "sensor_data": sensor_data,
        "detection_result": detection_result,
        "anomalies": anomalies,
        "ts": time.time(),
    })


def submit_update(weights):
    """Publish local YOLOv8 detection-head weights for FedAvg aggregation
    on Pi5. Only detection-head parameters travel — never raw images."""
    return _hive._publish(config.HIVEMQ_TOPIC_FED_SUBMIT, {
        "node_id": config.NODE_ID,
        "zone_id": config.ZONE_ID,
        "weights": weights,
        "ts": time.time(),
    })


def get_global_weights():
    """Return the most recently received aggregated global model, if any."""
    with _hive._lock:
        return _hive.latest_global_weights


def submit_label_proposal(label_entry):
    """Publish a newly-promoted 'unknown_label_N' (from label_discovery.py)
    so Pi5 can register it in the next federated round and every zone
    benefits from the discovery, per Claim 4."""
    return _hive._publish(config.HIVEMQ_TOPIC_LABEL_PROPOSAL, {
        "node_id": config.NODE_ID,
        "zone_id": config.ZONE_ID,
        **label_entry,
    })


def get_label_registry():
    """Return the latest confirmed shared label list broadcast by Pi5, so
    this node can adopt labels discovered by OTHER zones too."""
    with _hive._lock:
        return _hive.latest_label_registry
