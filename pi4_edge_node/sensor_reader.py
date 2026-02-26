"""MQTT subscriber — receives sensor data from ESP32 nodes."""

import json
import time
import logging
import paho.mqtt.client as mqtt
import config

log = logging.getLogger(__name__)


class SensorReader:
    """Subscribes to MQTT topics and stores the latest sensor readings."""

    def __init__(self):
        self.client = mqtt.Client(client_id=f"{config.NODE_ID}_reader")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.latest = {}          # {esp_node_id: {temperature, ph, turbidity, timestamp}}
        self.connected = False

    def start(self):
        """Connect to the MQTT broker and start the network loop."""
        try:
            self.client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
            self.client.loop_start()
            log.info("MQTT client started")
        except Exception as e:
            log.error("MQTT connect failed: %s", e)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        log.info("MQTT client stopped")

    # ── callbacks ────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe(config.MQTT_TOPIC_DATA)
            client.subscribe(config.MQTT_TOPIC_STATUS)
            log.info("Subscribed to MQTT topics")
        else:
            log.error("MQTT connect rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            topic = msg.topic

            if topic == config.MQTT_TOPIC_DATA:
                node_id = data.get("node_id", "unknown")
                self.latest[node_id] = {
                    "temperature": data.get("temperature", 0.0),
                    "ph": data.get("ph", 7.0),
                    "turbidity": data.get("turbidity", 0.0),
                    "timestamp": time.time(),
                }
                log.debug("Sensor data from %s: temp=%.2f pH=%.2f turb=%.1f",
                          node_id, data.get("temperature", 0),
                          data.get("ph", 0), data.get("turbidity", 0))

            elif topic == config.MQTT_TOPIC_STATUS:
                log.info("ESP32 status: %s", data)

        except json.JSONDecodeError:
            log.warning("Bad JSON on %s", msg.topic)

    # ── public helpers ───────────────────────────────────────

    def get_aggregated(self):
        """Return averaged sensor data across all connected ESP32 nodes."""
        if not self.latest:
            return {"temperature": 0.0, "ph": 7.0, "turbidity": 0.0, "node_count": 0}

        temps, phs, turbs = [], [], []
        for v in self.latest.values():
            if time.time() - v["timestamp"] < 60:   # ignore stale (>60 s)
                temps.append(v["temperature"])
                phs.append(v["ph"])
                turbs.append(v["turbidity"])

        if not temps:
            return {"temperature": 0.0, "ph": 7.0, "turbidity": 0.0, "node_count": 0}

        return {
            "temperature": sum(temps) / len(temps),
            "ph": sum(phs) / len(phs),
            "turbidity": sum(turbs) / len(turbs),
            "node_count": len(temps),
        }

    def detect_anomalies(self, data):
        """Check if temperature, pH, or turbidity is outside safe thresholds."""
        anomalies = {}
        t = data.get("temperature", 0)
        p = data.get("ph", 7)
        tu = data.get("turbidity", 0)
        if t < config.TEMP_MIN or t > config.TEMP_MAX:
            anomalies["temperature"] = True
        if p < config.PH_MIN or p > config.PH_MAX:
            anomalies["ph"] = True
        if tu < config.TURBIDITY_MIN or tu > config.TURBIDITY_MAX:
            anomalies["turbidity"] = True
        return anomalies
