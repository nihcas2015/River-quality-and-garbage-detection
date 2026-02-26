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
from federated_server import FederatedServer

# ── App setup ────────────────────────────────────────────────
# Serve the React production build from ../dashboard/frontend/build
BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "dashboard", "frontend", "build")
app = Flask(__name__, static_folder=None)   # static files handled by catch-all
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("server")


# ── Request logging ─────────────────────────────────────────
@app.before_request
def log_request():
    if request.path.startswith("/api/"):
        log.info("◀ %s %s from %s", request.method, request.path, request.remote_addr)


@app.after_request
def log_response(response):
    if request.path.startswith("/api/"):
        log.info("▶ %s %s → %s", request.method, request.path, response.status_code)
    return response


# ── In-memory data stores ────────────────────────────────────
nodes = {}            # {node_id: {node_type, registered_at, last_heartbeat, rounds}}
latest_readings = {}  # {node_id: {sensor_data, detection_result, anomalies, ts}}
alerts = []           # [{message, severity, type, node_id, timestamp}]
trash_events = []     # [{node_id, count, timestamp}]
fed_server = FederatedServer(min_nodes=1, round_timeout=300)


# ── Helper ───────────────────────────────────────────────────
def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def get_river_summary():
    """Aggregate latest readings across all nodes."""
    temps, phs, trash_total = [], [], 0
    anomaly_counts = {"temperature": 0, "ph": 0}
    sensor_stats = {}

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
        # Collect rolling sensor stats from the anomaly detector
        node_stats = v.get("anomalies", {}).get("stats")
        if node_stats:
            sensor_stats = node_stats   # latest node's stats

    return {
        "avg_temperature": sum(temps) / len(temps) if temps else 0,
        "avg_ph": sum(phs) / len(phs) if phs else 7,
        "total_trash_detected": trash_total,
        "anomalies": anomaly_counts,
        "node_count": len(latest_readings),
        "sensor_stats": sensor_stats,
    }


# ══════════════════════════════════════════════════════════════
#  REST API
# ══════════════════════════════════════════════════════════════

# ── Data submission (from Pi4 nodes) ─────────────────────────
@app.route("/api/data/submit", methods=["POST"])
def submit_data():
    d = request.json
    node_id = d.get("node_id", "unknown")
    log.info("Data received from %s  |  temp=%.1f  pH=%.2f  trash=%d",
             node_id,
             d.get("sensor_data", {}).get("temperature", 0),
             d.get("sensor_data", {}).get("ph", 0),
             d.get("detection_result", {}).get("trash_count", 0))
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

    # Generate alerts from the time-series anomaly list
    anomaly_list = d.get("anomalies", {}).get("anomaly_list", [])
    if anomaly_list:
        for a in anomaly_list:
            alerts.append({
                "message": a.get("message", "Unknown anomaly"),
                "severity": a.get("severity", "high"),
                "type": a.get("type", "anomaly"),
                "node_id": node_id,
                "sensor": a.get("sensor", ""),
                "value": a.get("value"),
                "timestamp": now_iso(),
            })
    else:
        # Backward-compatible: simple boolean flags
        for key, flagged in d.get("anomalies", {}).items():
            if flagged is True:
                alerts.append({
                    "message": f"{key} anomaly from {node_id}",
                    "severity": "high",
                    "type": "threshold",
                    "node_id": node_id,
                    "sensor": key,
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
    log.info("Node registered: %s (type: %s)", nid, d.get("node_type"))
    return jsonify({"status": "registered", "node_id": nid})


@app.route("/api/federation/heartbeat", methods=["POST"])
def node_heartbeat():
    nid = request.json.get("node_id")
    if nid in nodes:
        nodes[nid]["last_heartbeat"] = now_iso()
        log.debug("Heartbeat from %s", nid)
    else:
        log.warning("Heartbeat from unknown node: %s", nid)
    return jsonify({"status": "ok"})


@app.route("/api/federation/submit_update", methods=["POST"])
def submit_update():
    """Receive local model weights from an edge node for FedAvg."""
    d = request.json
    nid = d.get("node_id")
    weights = d.get("weights")
    if not nid or weights is None:
        return jsonify({"error": "missing node_id or weights"}), 400
    prev_round = fed_server.current_round
    fed_server.receive_update(nid, weights)
    # Update participation counter
    if nid in nodes:
        nodes[nid]["rounds_participated"] = fed_server.current_round
    log.info("Federation update from %s (%d values) — round %d→%d",
             nid, len(weights), prev_round, fed_server.current_round)
    return jsonify({"status": "ok", "round": fed_server.current_round})


@app.route("/api/federation/global_weights", methods=["GET"])
def global_weights():
    return jsonify(fed_server.get_global_weights())


@app.route("/api/federation/status", methods=["GET"])
def federation_status():
    active = sum(1 for n in nodes.values()
                 if (datetime.utcnow() - datetime.fromisoformat(
                     n["last_heartbeat"].rstrip("Z"))).total_seconds() < 60)
    return jsonify({
        "total_nodes": len(nodes),
        "active_nodes": active,
        "global_round": fed_server.current_round,
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


# Catch-all for unknown /api/* paths — returns 404 instead of index.html
@app.route("/api/<path:path>")
def api_not_found(path):
    return jsonify({"error": f"Unknown API endpoint: /api/{path}"}), 404


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
                "global_round": fed_server.current_round,
                "nodes": list(nodes.values()),
            },
            "latest_readings": latest_readings,
            "alerts": alerts[-20:],
        }
        socketio.emit("river_update", payload)


# ── Start ────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=== Pi5 Central Server starting ===")
    log.info("BUILD_DIR = %s (exists: %s)", BUILD_DIR, os.path.isdir(BUILD_DIR))
    log.info("Listening on http://0.0.0.0:5000")
    socketio.start_background_task(broadcast_loop)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
