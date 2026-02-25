"""
Pi5 Central Server — REST API + WebSocket + Dashboard hosting.

Receives data from Pi4 edge nodes, aggregates it,
pushes live updates via WebSocket, and serves the React dashboard.
"""

import os
import time
import logging
import threading
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

# ── App setup ────────────────────────────────────────────────
# Serve the React production build from ../dashboard/frontend/build
BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "frontend", "build")
app = Flask(__name__, static_folder=BUILD_DIR, static_url_path="")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("server")

# ── In-memory data stores ────────────────────────────────────
nodes = {}            # {node_id: {node_type, registered_at, last_heartbeat, rounds}}
latest_readings = {}  # {node_id: {sensor_data, detection_result, anomalies, ts}}
alerts = []           # [{message, severity, type, node_id, timestamp}]
trash_events = []     # [{node_id, count, timestamp}]
federation = {"global_round": 0, "weights": None}


# ── Helper ───────────────────────────────────────────────────
def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def get_river_summary():
    """Aggregate latest readings across all nodes."""
    temps, phs, trash_total = [], [], 0
    anomaly_counts = {"temperature": 0, "ph": 0}

    for v in latest_readings.values():
        sd = v.get("sensor_data", {})
        t = sd.get("temperature")
        p = sd.get("ph")
        if t is not None:
            temps.append(t)
        if p is not None:
            phs.append(p)
        trash_total += v.get("detection_result", {}).get("trash_count", 0)
        for k in anomaly_counts:
            if v.get("anomalies", {}).get(k):
                anomaly_counts[k] += 1

    return {
        "avg_temperature": sum(temps) / len(temps) if temps else 0,
        "avg_ph": sum(phs) / len(phs) if phs else 7,
        "total_trash_detected": trash_total,
        "anomalies": anomaly_counts,
        "node_count": len(latest_readings),
    }


# ══════════════════════════════════════════════════════════════
#  REST API
# ══════════════════════════════════════════════════════════════

# ── Data submission (from Pi4 nodes) ─────────────────────────
@app.route("/api/data/submit", methods=["POST"])
def submit_data():
    d = request.json
    node_id = d.get("node_id", "unknown")
    latest_readings[node_id] = {
        "sensor_data": d.get("sensor_data", {}),
        "detection_result": d.get("detection_result", {}),
        "anomalies": d.get("anomalies", {}),
        "timestamp": now_iso(),
    }

    # Store trash events
    tc = d.get("detection_result", {}).get("trash_count", 0)
    if tc > 0:
        trash_events.append({"node_id": node_id, "count": tc, "timestamp": now_iso()})
        if len(trash_events) > 500:
            trash_events[:] = trash_events[-500:]

    # Generate alerts for anomalies
    for key, flagged in d.get("anomalies", {}).items():
        if flagged:
            alerts.append({
                "message": f"{key} anomaly from {node_id}",
                "severity": "high",
                "type": "anomaly",
                "node_id": node_id,
                "timestamp": now_iso(),
            })
    if len(alerts) > 200:
        alerts[:] = alerts[-200:]

    return jsonify({"status": "ok"})


# ── Federation ───────────────────────────────────────────────
@app.route("/api/federation/register", methods=["POST"])
def register_node():
    d = request.json
    nid = d.get("node_id")
    nodes[nid] = {
        "node_id": nid,
        "node_type": d.get("node_type", "unknown"),
        "registered_at": now_iso(),
        "last_heartbeat": now_iso(),
        "rounds_participated": 0,
    }
    log.info("Node registered: %s", nid)
    return jsonify({"status": "registered"})


@app.route("/api/federation/heartbeat", methods=["POST"])
def node_heartbeat():
    nid = request.json.get("node_id")
    if nid in nodes:
        nodes[nid]["last_heartbeat"] = now_iso()
    return jsonify({"status": "ok"})


@app.route("/api/federation/global_weights", methods=["GET"])
def global_weights():
    return jsonify({"round": federation["global_round"], "weights": federation["weights"]})


@app.route("/api/federation/status", methods=["GET"])
def federation_status():
    active = sum(1 for n in nodes.values()
                 if (datetime.utcnow() - datetime.fromisoformat(
                     n["last_heartbeat"].rstrip("Z"))).total_seconds() < 60)
    return jsonify({
        "total_nodes": len(nodes),
        "active_nodes": active,
        "global_round": federation["global_round"],
        "nodes": list(nodes.values()),
    })


# ── Dashboard endpoints ──────────────────────────────────────
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
    return jsonify({
        "trash_events": trash_events[-limit:],
        "total_count": sum(e["count"] for e in trash_events),
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "uptime": time.process_time()})


# ── Serve React dashboard ────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_dashboard(path):
    """Serve React build files. Falls back to index.html for client-side routing."""
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
                                        n["last_heartbeat"].rstrip("Z")
                                    )).total_seconds() < 60),
                "global_round": federation["global_round"],
                "nodes": list(nodes.values()),
            },
            "latest_readings": latest_readings,
            "alerts": alerts[-20:],
        }
        socketio.emit("river_update", payload)


# ── Start ────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=== Pi5 Central Server starting ===")
    socketio.start_background_task(broadcast_loop)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
