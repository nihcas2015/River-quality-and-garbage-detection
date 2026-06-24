"""MQTT subscriber — receives sensor data from ESP32 nodes via HiveMQ cloud."""

import json
import time
import logging
import ssl
import paho.mqtt.client as mqtt
import config

log = logging.getLogger(__name__)


class SensorReader:
    """Subscribes to HiveMQ cloud MQTT topics and stores latest sensor readings.
    
    Zones can be any distance apart — each ESP32 connects to HiveMQ independently
    over the internet. No local WiFi range limitation.
    """

    def __init__(self):
        self.client = mqtt.Client(
            client_id=f"{config.NODE_ID}_reader",
            protocol=mqtt.MQTTv311,
        )
        # HiveMQ cloud requires username/password + TLS
        self.client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
        if config.MQTT_USE_TLS:
            self.client.tls_set(tls_version=ssl.PROTOCOL_TLS)

        self.client.on_connect    = self._on_connect
        self.client.on_message    = self._on_message
        self.client.on_disconnect = self._on_disconnect

        self.latest   = {}     # {esp_node_id: {temperature, ph, turbidity, timestamp}}
        self.connected = False

    def start(self):
        """Connect to HiveMQ cloud and start the network loop."""
        try:
            log.info("Connecting to HiveMQ cloud: %s:%d ...",
                     config.MQTT_BROKER, config.MQTT_PORT)
            self.client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
            self.client.loop_start()

            # Wait up to 8 seconds for TLS handshake + connect
            deadline = time.time() + 8.0
            while not self.connected and time.time() < deadline:
                time.sleep(0.1)

            if self.connected:
                log.info("✓ HiveMQ cloud MQTT connected (%s:%d)",
                         config.MQTT_BROKER, config.MQTT_PORT)
            else:
                log.warning("⚠ HiveMQ connection pending — check credentials in config.py")
        except Exception as e:
            log.error("✗ HiveMQ connection failed: %s", e)
            log.error("  → Check MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD in config.py")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        log.info("MQTT client stopped")

    # ── callbacks ─────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        RC_CODES = {
            0: "Connected successfully",
            1: "Wrong MQTT protocol version",
            2: "Invalid client ID",
            3: "Broker unavailable",
            4: "Wrong username or password",
            5: "Not authorised",
        }
        if rc == 0:
            self.connected = True
            client.subscribe(config.MQTT_TOPIC_DATA)
            client.subscribe(config.MQTT_TOPIC_STATUS)
            log.info("✓ Subscribed: %s, %s",
                     config.MQTT_TOPIC_DATA, config.MQTT_TOPIC_STATUS)
        else:
            self.connected = False
            reason = RC_CODES.get(rc, f"Unknown rc={rc}")
            log.error("✗ HiveMQ connect failed: %s", reason)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            log.warning("⚠ HiveMQ disconnected unexpectedly (rc=%d), auto-reconnecting...", rc)

    def _on_message(self, client, userdata, msg):
        try:
            data  = json.loads(msg.payload.decode())
            topic = msg.topic

            if topic == config.MQTT_TOPIC_DATA:
                node_id = data.get("node_id", "unknown")
                temp    = data.get("temperature", 0.0)
                ph      = data.get("ph", 7.0)
                turb    = data.get("turbidity", 0.0)

                if -50 < temp < 50 and 0 <= ph <= 14 and 0 <= turb <= 3000:
                    self.latest[node_id] = {
                        "temperature": temp,
                        "ph":          ph,
                        "turbidity":   turb,
                        "timestamp":   time.time(),
                    }
                    log.debug("✓ Sensor [%s]: temp=%.2f pH=%.2f turb=%.1f",
                              node_id, temp, ph, turb)
                else:
                    log.warning("⚠ Out-of-range values from %s: "
                                "temp=%.2f pH=%.2f turb=%.1f — ignored",
                                node_id, temp, ph, turb)

            elif topic == config.MQTT_TOPIC_STATUS:
                log.info("ESP32 status: %s", data)

        except json.JSONDecodeError as e:
            log.warning("⚠ Bad JSON on %s: %s", msg.topic, e)
        except Exception as e:
            log.error("✗ Message handler error: %s", e)

    # ── public helpers ─────────────────────────────────────────

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
            "ph":          sum(phs)   / len(phs),
            "turbidity":   sum(turbs) / len(turbs),
            "node_count":  len(temps),
        }

    def detect_anomalies(self, data):
        """Check if temperature, pH, or turbidity is outside safe thresholds."""
        anomalies = {}
        t  = data.get("temperature", 0)
        p  = data.get("ph", 7)
        tu = data.get("turbidity", 0)
        if t < config.TEMP_MIN or t > config.TEMP_MAX:
            anomalies["temperature"] = True
        if p < config.PH_MIN or p > config.PH_MAX:
            anomalies["ph"] = True
        if tu < config.TURBIDITY_MIN or tu > config.TURBIDITY_MAX:
            anomalies["turbidity"] = True
        return anomalies
