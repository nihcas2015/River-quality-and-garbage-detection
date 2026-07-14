"""
Pi5 Central Server — HiveMQ MQTT ingestion + REST/WebSocket dashboard.

Per the patent disclosure (Claim 3), edge nodes reach this server ONLY
via HiveMQ Cloud MQTT — there is no HTTP ingestion anymore. This file:
  1. Connects to HiveMQ Cloud and subscribes to wildcard zone topics
     (river/+/register, .../heartbeat, .../data,
      .../federation/submit, .../label_discovery/proposal)
  2. Feeds incoming messages into the same in-memory stores / alert /
     trash-aggregation logic the dashboard already relies on
  3. Runs FedAvg (federated_server.py) and republishes the global model
     to each zone's river/{zone_id}/federation/global topic
  4. Republishes the confirmed label registry to river/label_registry/global
  5. Still serves the REST dashboard endpoints + WebSocket broadcast
"""

import os
import json
import time
import random
import logging
import threading
from datetime import datetime

import paho.mqtt.client as mqtt
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

import config
from federated_server import FederatedServer

# ── App setup ────────────────────────────────────────────────
BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "dashboard", "frontend", "build")
app = Flask(__name__, static_folder=None)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("server")

DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
DEMO_ZONES = ["zone_1", "zone_2", "zone_3"]
DEMO_TRASH_CLASSES = ["Plastic", "Paper", "Metal", "Glass", "Organic", "Textile"]

# ── In-memory data stores ────────────────────────────────────
nodes = {}            # {node_id: {node_id, zone_id, node_type, registered_at, last_heartbeat, rounds}}
latest_readings = {}  # {node_id: {zone_id, sensor_data, detection_result, anomalies, timestamp}}
alerts = []
trash_events = []
trash_class_totals = {}
system_trace = []
fed_server = FederatedServer(min_nodes=config.FED_MIN_NODES)


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def trace(event, source="server", detail=""):
    entry = {"event": event, "source": source, "detail": str(detail)[:300],
             "timestamp": now_iso()}
    system_trace.append(entry)
    if len(system_trace) > 500:
        system_trace[:] = system_trace[-500:]


def get_river_summary():
    temps, phs, turbs, trash_total = [], [], [], 0
    anomaly_counts = {"temperature": 0, "ph": 0, "turbidity": 0}
    sensor_stats = {}
    class_counts_agg = {}

    for v in latest_readings.values():
        sd = v.get("sensor_data", {})
        if sd.get("temperature") is not None:
            temps.append(sd["temperature"])
        if sd.get("ph") is not None:
            phs.append(sd["ph"])
        if sd.get("turbidity") is not None:
            turbs.append(sd["turbidity"])
        trash_total += v.get("detection_result", {}).get("trash_count", 0)
        cc = v.get("detection_result", {}).get("class_counts", {})
        for cls_name, cnt in cc.items():
            class_counts_agg[cls_name] = class_counts_agg.get(cls_name, 0) + cnt
        for k in anomaly_counts:
            if v.get("anomalies", {}).get(k):
                anomaly_counts[k] += 1
        node_stats = v.get("anomalies", {}).get("stats")
        if node_stats:
            sensor_stats = node_stats

    return {
        "avg_temperature": sum(temps) / len(temps) if temps else 0,
        "avg_ph": sum(phs) / len(phs) if phs else 7,
        "avg_turbidity": sum(turbs) / len(turbs) if turbs else 0,
        "total_trash_detected": trash_total,
        "trash_class_counts": class_counts_agg,
        "trash_class_totals": trash_class_totals,
        "anomalies": anomaly_counts,
        "node_count": len(latest_readings),
        "sensor_stats": sensor_stats,
        "unknown_objects": fed_server.get_unknown_objects_summary(),
    }


# ══════════════════════════════════════════════════════════════
#  Ingestion logic (shared by real MQTT messages AND the demo loop)
# ══════════════════════════════════════════════════════════════

def handle_register(d):
    nid = d.get("node_id")
    zone_id = d.get("zone_id", "unknown_zone")
    if not nid:
        return
    nodes[nid] = {
        "node_id": nid,
        "zone_id": zone_id,
        "node_type": d.get("node_type", "unknown"),
        "registered_at": now_iso(),
        "last_heartbeat": now_iso(),
        "rounds_participated": nodes.get(nid, {}).get("rounds_participated", 0),
    }
    log.info("Node registered: %s (zone=%s)", nid, zone_id)
    trace("node_registered", source=nid, detail=zone_id)


def handle_heartbeat(d):
    nid = d.get("node_id")
    if nid in nodes:
        nodes[nid]["last_heartbeat"] = now_iso()
    else:
        log.warning("Heartbeat from unregistered node: %s", nid)


def handle_data(d):
    nid = d.get("node_id", "unknown")
    zone_id = d.get("zone_id", "unknown_zone")
    sensor_data = d.get("sensor_data", {})
    detection_result = d.get("detection_result", {})
    anomalies = d.get("anomalies", {})

    log.info("Data from %s/%s | temp=%.1f pH=%.2f turb=%.0f trash=%d",
             zone_id, nid, sensor_data.get("temperature", 0),
             sensor_data.get("ph", 0), sensor_data.get("turbidity", 0),
             detection_result.get("trash_count", 0))

    latest_readings[nid] = {
        "zone_id": zone_id,
        "sensor_data": sensor_data,
        "detection_result": detection_result,
        "anomalies": anomalies,
        "timestamp": now_iso(),
    }
    trace("data_received", source=nid,
          detail=f"zone={zone_id} temp={sensor_data.get('temperature', 0):.1f} "
                 f"trash={detection_result.get('trash_count', 0)}")

    tc = detection_result.get("trash_count", 0)
    cc = detection_result.get("class_counts", {})
    if tc > 0:
        trash_events.append({"node_id": nid, "zone_id": zone_id, "count": tc,
                              "class_counts": cc, "timestamp": now_iso()})
        if len(trash_events) > 500:
            trash_events[:] = trash_events[-500:]
        for cls_name, cnt in cc.items():
            trash_class_totals[cls_name] = trash_class_totals.get(cls_name, 0) + cnt
        trace("trash_detected", source=nid, detail=f"{tc} items — classes: {cc}")

    anomaly_list = anomalies.get("anomaly_list", [])
    if anomaly_list:
        for a in anomaly_list:
            alerts.append({
                "message": a.get("message", "Unknown anomaly"),
                "severity": a.get("severity", "high"),
                "type": a.get("type", "anomaly"),
                "node_id": nid, "zone_id": zone_id,
                "sensor": a.get("sensor", ""), "value": a.get("value"),
                "timestamp": now_iso(),
            })
    else:
        for key, flagged in anomalies.items():
            if flagged is True:
                alerts.append({
                    "message": f"{key} anomaly from {nid}",
                    "severity": "high", "type": "threshold",
                    "node_id": nid, "zone_id": zone_id, "sensor": key,
                    "timestamp": now_iso(),
                })
    if len(alerts) > 200:
        alerts[:] = alerts[-200:]


def handle_fed_submit(d):
    """A zone submitted local YOLOv8 detection-head weights. Aggregate and,
    if a new round completed, publish the updated global model back to
    EVERY known zone's river/{zone_id}/federation/global topic."""
    nid = d.get("node_id")
    zone_id = d.get("zone_id", "unknown_zone")
    weights = d.get("weights")
    if not nid or weights is None:
        return
    prev_round = fed_server.current_round
    new_round_ready = fed_server.receive_update(nid, zone_id, weights)
    if nid in nodes:
        nodes[nid]["rounds_participated"] = fed_server.current_round
    trace("federation_update", source=nid,
          detail=f"zone={zone_id} {len(weights)} weights — round {prev_round}->{fed_server.current_round}")

    if new_round_ready:
        payload = fed_server.get_global_weights()
        for z in list(fed_server.known_zones):
            topic = config.TOPIC_FED_GLOBAL_PUB.format(zone_id=z)
            mqtt_publish(topic, payload)
        log.info("Global model round %d broadcast to %d zone(s)",
                  fed_server.current_round, len(fed_server.known_zones))


def handle_label_proposal(d):
    """A zone autonomously discovered a new waste category (Claim 4).
    Confirm it into the global registry and broadcast to ALL zones so
    every edge node adopts it, even ones that didn't discover it."""
    zone_id = d.get("zone_id", "unknown_zone")
    label = d.get("label")
    if not label:
        return
    changed = fed_server.register_label_proposal(
        zone_id, label,
        cluster_id=d.get("cluster_id"), sample_count=d.get("sample_count"),
        node_id=d.get("node_id"), discovered_at=d.get("discovered_at"),
    )
    trace("label_discovered", source=d.get("node_id", zone_id),
          detail=f"'{label}' from zone={zone_id}")
    if changed:
        mqtt_publish(config.TOPIC_LABEL_REGISTRY_PUB, fed_server.get_label_registry())
        log.warning("Label registry v%d broadcast (classes=%s)",
                    fed_server.registry_version, fed_server.confirmed_classes)


# ══════════════════════════════════════════════════════════════
#  HiveMQ Cloud MQTT client
# ══════════════════════════════════════════════════════════════

_mqtt = mqtt.Client(client_id=config.HIVEMQ_CLIENT_ID, clean_session=True)
_mqtt_connected = False


def _topic_zone(topic):
    """Extract zone_id from a 'river/{zone_id}/...' topic string."""
    parts = topic.split("/")
    return parts[1] if len(parts) > 1 else "unknown_zone"


def _on_connect(client, userdata, flags, rc):
    global _mqtt_connected
    if rc == 0:
        _mqtt_connected = True
        client.subscribe([
            (config.TOPIC_REGISTER_SUB, config.HIVEMQ_QOS),
            (config.TOPIC_HEARTBEAT_SUB, config.HIVEMQ_QOS),
            (config.TOPIC_DATA_SUB, config.HIVEMQ_QOS),
            (config.TOPIC_FED_SUBMIT_SUB, config.HIVEMQ_QOS),
            (config.TOPIC_LABEL_PROPOSAL_SUB, config.HIVEMQ_QOS),
        ])
        log.info("Connected to HiveMQ Cloud (%s) — subscribed to all zone wildcards",
                  config.HIVEMQ_HOST)
    else:
        log.error("HiveMQ Cloud connect rc=%d (check credentials/cluster URL)", rc)


def _on_disconnect(client, userdata, rc):
    global _mqtt_connected
    _mqtt_connected = False
    if rc != 0:
        log.warning("Unexpected HiveMQ Cloud disconnect (rc=%d) — paho will auto-reconnect", rc)


def _on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        log.warning("Bad JSON on %s", msg.topic)
        return

    zone_id = _topic_zone(msg.topic)
    d.setdefault("zone_id", zone_id)

    if msg.topic.endswith("/register"):
        handle_register(d)
    elif msg.topic.endswith("/heartbeat"):
        handle_heartbeat(d)
    elif msg.topic.endswith("/data"):
        handle_data(d)
    elif msg.topic.endswith("/federation/submit"):
        handle_fed_submit(d)
    elif msg.topic.endswith("/label_discovery/proposal"):
        handle_label_proposal(d)
    else:
        log.debug("Unhandled topic: %s", msg.topic)


def mqtt_publish(topic, payload_dict):
    if not _mqtt_connected:
        log.debug("Publish skipped — not connected (topic=%s)", topic)
        return False
    try:
        body = json.dumps(payload_dict)
        if len(body.encode()) > config.HIVEMQ_MAX_PAYLOAD_BYTES:
            log.error("Payload for %s exceeds max size, dropping", topic)
            return False
        info = _mqtt.publish(topic, body, qos=config.HIVEMQ_QOS)
        return info.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception as e:
        log.error("Publish to %s failed: %s", topic, e)
        return False


def start_mqtt():
    if "xxxxxxxxxxxx" in config.HIVEMQ_HOST or config.HIVEMQ_PASSWORD == "CHANGE_ME":
        log.error("HiveMQ Cloud credentials are still placeholders! "
                   "Set HIVEMQ_HOST / HIVEMQ_USERNAME / HIVEMQ_PASSWORD in config.py")
        return False
    _mqtt.username_pw_set(config.HIVEMQ_USERNAME, config.HIVEMQ_PASSWORD)
    if config.HIVEMQ_USE_TLS:
        _mqtt.tls_set()
    _mqtt.on_connect = _on_connect
    _mqtt.on_disconnect = _on_disconnect
    _mqtt.on_message = _on_message
    try:
        _mqtt.connect(config.HIVEMQ_HOST, config.HIVEMQ_PORT, keepalive=config.HIVEMQ_KEEPALIVE)
        _mqtt.loop_start()
        return True
    except Exception as e:
        log.error("HiveMQ Cloud connect failed: %s", e)
        return False


# ══════════════════════════════════════════════════════════════
#  REST — dashboard read endpoints (unchanged surface for frontend)
# ══════════════════════════════════════════════════════════════

@app.route("/api/federation/status", methods=["GET"])
def federation_status():
    active = sum(1 for n in nodes.values()
                 if (datetime.utcnow() - datetime.fromisoformat(
                     n["last_heartbeat"].rstrip("Z"))).total_seconds() < config.NODE_STALE_TIMEOUT)
    return jsonify({
        "total_nodes": len(nodes),
        "active_nodes": active,
        "global_round": fed_server.current_round,
        "nodes": list(nodes.values()),
        "label_registry": fed_server.get_label_registry(),
    })


@app.route("/api/dashboard/river_data", methods=["GET"])
def river_data():
    return jsonify(get_river_summary())


@app.route("/api/dashboard/latest_readings", methods=["GET"])
def get_latest():
    return jsonify(latest_readings)


@app.route("/api/dashboard/alerts", methods=["GET"])
def get_alerts():
    return jsonify({"alerts": alerts[-50:]})


@app.route("/api/dashboard/trash_history", methods=["GET"])
def trash_history():
    limit = request.args.get("limit", 100, type=int)
    hours = request.args.get("hours", type=int)
    events = trash_events
    if hours:
        cutoff = datetime.utcnow().timestamp() - hours * 3600
        events = [
            e for e in trash_events
            if datetime.fromisoformat(e["timestamp"].rstrip("Z")).timestamp() >= cutoff
        ]
    events = events[-limit:]
    class_totals_in_range = {}
    for e in events:
        for cls_name, cnt in e.get("class_counts", {}).items():
            class_totals_in_range[cls_name] = class_totals_in_range.get(cls_name, 0) + cnt
    return jsonify({
        "trash_events": events,
        "total_count": sum(e["count"] for e in events),
        "class_totals": class_totals_in_range or trash_class_totals,
    })


@app.route("/api/dashboard/label_registry", methods=["GET"])
def label_registry():
    return jsonify(fed_server.get_label_registry())


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "uptime": time.process_time(),
                     "mqtt_connected": _mqtt_connected})


@app.route("/api/system/trace", methods=["GET"])
def get_trace():
    limit = request.args.get("limit", 100, type=int)
    return jsonify({"trace": system_trace[-limit:], "total_events": len(system_trace)})


@app.route("/api/system/diagnostics", methods=["GET"])
def diagnostics():
    active, stale = 0, 0
    for n in nodes.values():
        elapsed = (datetime.utcnow() - datetime.fromisoformat(
            n["last_heartbeat"].rstrip("Z"))).total_seconds()
        if elapsed < config.NODE_STALE_TIMEOUT:
            active += 1
        else:
            stale += 1
    return jsonify({
        "server": {"uptime_s": round(time.process_time(), 2),
                   "nodes_registered": len(nodes), "nodes_active": active, "nodes_stale": stale,
                   "mqtt_connected": _mqtt_connected},
        "data_pipeline": {"total_readings": len(latest_readings),
                          "total_trash_events": len(trash_events),
                          "trash_class_totals": trash_class_totals,
                          "total_alerts": len(alerts)},
        "federation": {"current_round": fed_server.current_round,
                      "pending_updates": len(fed_server.updates),
                      "has_global_model": fed_server.global_weights is not None,
                      "label_registry_version": fed_server.registry_version,
                      "confirmed_classes": fed_server.confirmed_classes},
        "trace_log_size": len(system_trace),
        "timestamp": now_iso(),
        "demo_mode": DEMO_MODE,
    })


@app.route("/api/<path:path>")
def api_not_found(path):
    return jsonify({"error": f"Unknown API endpoint: /api/{path}"}), 404


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_dashboard(path):
    if path and os.path.exists(os.path.join(BUILD_DIR, path)):
        return send_from_directory(BUILD_DIR, path)
    return send_from_directory(BUILD_DIR, "index.html")


# ══════════════════════════════════════════════════════════════
#  WebSocket — push live data to dashboard every 5 s
# ══════════════════════════════════════════════════════════════

def broadcast_loop():
    while True:
        socketio.sleep(5)
        payload = {
            "river_data": get_river_summary(),
            "federation_status": {
                "total_nodes": len(nodes),
                "active_nodes": sum(1 for n in nodes.values()
                                    if (datetime.utcnow() - datetime.fromisoformat(
                                        n["last_heartbeat"].rstrip("Z"))).total_seconds()
                                    < config.NODE_STALE_TIMEOUT),
                "global_round": fed_server.current_round,
                "nodes": list(nodes.values()),
            },
            "latest_readings": latest_readings,
            "alerts": alerts[-20:],
            "trash_class_totals": trash_class_totals,
            "label_registry": fed_server.get_label_registry(),
        }
        socketio.emit("river_update", payload)


# ══════════════════════════════════════════════════════════════
#  DEMO DATA SIMULATOR — feeds the SAME handle_* functions the real
#  MQTT callback uses, so behaviour matches real Pi4 hardware exactly.
# ══════════════════════════════════════════════════════════════

def _demo_register_zones():
    for i, zone in enumerate(DEMO_ZONES, start=1):
        nid = f"pi4_edge_0{i}"
        handle_register({"node_id": nid, "zone_id": zone, "node_type": "raspberry_pi4"})


def _demo_generate_reading(node_id, zone_id):
    base_temp = 22 + random.uniform(-3, 3)
    base_ph = 7.1 + random.uniform(-0.6, 0.6)
    base_turb = 15 + random.uniform(-8, 25)

    anomaly_list = []
    if random.random() < 0.08:
        spike_sensor = random.choice(["temperature", "ph", "turbidity"])
        if spike_sensor == "temperature":
            base_temp += random.uniform(6, 10)
        elif spike_sensor == "ph":
            base_ph += random.choice([-1, 1]) * random.uniform(1.0, 1.8)
        else:
            base_turb += random.uniform(40, 80)
        anomaly_list.append({
            "message": f"{spike_sensor.capitalize()} spike detected at {node_id}",
            "severity": random.choice(["medium", "high"]),
            "type": "threshold", "sensor": spike_sensor,
            "value": round({"temperature": base_temp, "ph": base_ph,
                             "turbidity": base_turb}[spike_sensor], 2),
        })

    trash_count = random.choices([0, 1, 2, 3, 4], weights=[40, 25, 15, 12, 8])[0]
    class_counts = {}
    for _ in range(trash_count):
        cls = random.choice(DEMO_TRASH_CLASSES)
        class_counts[cls] = class_counts.get(cls, 0) + 1

    return {
        "node_id": node_id, "zone_id": zone_id,
        "sensor_data": {"temperature": round(base_temp, 2), "ph": round(base_ph, 2),
                        "turbidity": round(max(base_turb, 0), 1)},
        "detection_result": {"trash_count": trash_count, "class_counts": class_counts},
        "anomalies": {
            "temperature": any(a["sensor"] == "temperature" for a in anomaly_list),
            "ph": any(a["sensor"] == "ph" for a in anomaly_list),
            "turbidity": any(a["sensor"] == "turbidity" for a in anomaly_list),
            "anomaly_list": anomaly_list,
            "stats": {
                "temperature": {"mean": round(base_temp, 2), "std": round(random.uniform(0.5, 2.0), 2)},
                "ph": {"mean": round(base_ph, 2), "std": round(random.uniform(0.1, 0.4), 2)},
                "turbidity": {"mean": round(base_turb, 1), "std": round(random.uniform(2, 8), 2)},
            },
        },
    }


def demo_data_loop():
    log.info("=== DEMO MODE ACTIVE — generating simulated MQTT-equivalent data ===")
    log.info("Set DEMO_MODE=0 once real Pi4 hardware is connected via HiveMQ.")
    _demo_register_zones()
    round_num = 0
    demo_nodes = [(f"pi4_edge_0{i}", z) for i, z in enumerate(DEMO_ZONES, start=1)]
    while True:
        round_num += 1
        for nid, zone in demo_nodes:
            handle_data(_demo_generate_reading(nid, zone))
            if nid in nodes:
                nodes[nid]["last_heartbeat"] = now_iso()

        if round_num % 3 == 0:
            nid, zone = random.choice(demo_nodes)
            fake_weights = [random.uniform(-1, 1) for _ in range(10)]
            handle_fed_submit({"node_id": nid, "zone_id": zone, "weights": fake_weights})

        time.sleep(6)


# ── Start ────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000

if __name__ == "__main__":
    log.info("=== Pi5 Central Server starting ===")
    log.info("BUILD_DIR = %s (exists: %s)", BUILD_DIR, os.path.isdir(BUILD_DIR))
    log.info("Listening on http://%s:%d", SERVER_HOST, SERVER_PORT)
    log.info("DEMO_MODE = %s", DEMO_MODE)

    if not DEMO_MODE:
        if not start_mqtt():
            log.error("Could not start HiveMQ Cloud client — check config.py credentials.")
    else:
        log.info("DEMO_MODE=1 — skipping real HiveMQ connection, using simulator instead")

    socketio.start_background_task(broadcast_loop)
    if DEMO_MODE:
        threading.Thread(target=demo_data_loop, daemon=True).start()
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=False)