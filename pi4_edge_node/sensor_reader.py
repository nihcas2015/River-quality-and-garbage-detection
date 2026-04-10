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
            log.info("Attempting MQTT connection to %s:%d...", 
                     config.MQTT_BROKER, config.MQTT_PORT)
            self.client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
            self.client.loop_start()
            
            # Wait up to 5 seconds for connection to establish
            import time
            max_wait = 5.0
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < max_wait:
                time.sleep(0.1)
            
            if self.connected:
                log.info("✓ MQTT connected successfully to %s:%d", 
                         config.MQTT_BROKER, config.MQTT_PORT)
            else:
                log.warning("⚠ MQTT connection pending (timeout), will retry...")
        except Exception as e:
            log.error("✗ MQTT connection failed: %s", e)
            log.error("  → Check if Mosquitto is running: 'sudo systemctl status mosquitto'")
            log.error("  → Or start it: 'sudo systemctl start mosquitto'")

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
            log.info("✓ Subscribed to MQTT topics: %s, %s", 
                     config.MQTT_TOPIC_DATA, config.MQTT_TOPIC_STATUS)
        else:
            self.connected = False
            log.error("✗ MQTT connection failed with rc=%d", rc)
            log.error("  → rc=1: MQTT version rejected")
            log.error("  → rc=2: Invalid client identifier")
            log.error("  → rc=3: Server unavailable")
            log.error("  → rc=4: Bad username/password")
            log.error("  → rc=5: Not authorized")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            topic = msg.topic

            if topic == config.MQTT_TOPIC_DATA:
                node_id = data.get("node_id", "unknown")
                temp = data.get("temperature", 0.0)
                ph = data.get("ph", 7.0)
                turb = data.get("turbidity", 0.0)
                
                # Validate sensor readings are within expected ranges
                if -50 < temp < 50 and 0 <= ph <= 14 and 0 <= turb <= 3000:
                    self.latest[node_id] = {
                        "temperature": temp,
                        "ph": ph,
                        "turbidity": turb,
                        "timestamp": time.time(),
                    }
                    log.debug("✓ Sensor data from %s: temp=%.2f pH=%.2f turb=%.1f",
                              node_id, temp, ph, turb)
                else:
                    log.warning("⚠ Invalid sensor values from %s: temp=%.2f pH=%.2f turb=%.1f",
                                node_id, temp, ph, turb)

            elif topic == config.MQTT_TOPIC_STATUS:
                log.info("ESP32 status: %s", data)

        except json.JSONDecodeError as e:
            log.warning("⚠ Bad JSON on %s: %s", msg.topic, e)
        except Exception as e:
            log.error("✗ Message handler error: %s", e)

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
