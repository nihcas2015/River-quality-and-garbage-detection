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
trash_events = []     # [{node_id, count, class_counts, timestamp}]
trash_class_totals = {}  # {class_name: total_count} aggregated across all events
system_trace = []     # [{event, source, detail, timestamp}] for diagnostics
fed_server = FederatedServer(min_nodes=1, round_timeout=300)

# Unknown object discovery — populated by /api/discovery/new_label
# {label: {node_id, cluster_id, sighting_count, first_seen, last_seen, zones}}
unknown_labels = {}


# ── Helper ───────────────────────────────────────────────────
def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def trace(event, source="server", detail=""):
    """Append an entry to the system trace log."""
    entry = {"event": event, "source": source, "detail": str(detail)[:300],
             "timestamp": now_iso()}
    system_trace.append(entry)
    if len(system_trace) > 500:
        system_trace[:] = system_trace[-500:]


def get_river_summary():
    """Aggregate latest readings across all nodes."""
    temps, phs, turbs, trash_total = [], [], [], 0
    anomaly_counts = {"temperature": 0, "ph": 0, "turbidity": 0}
    sensor_stats = {}
    class_counts_agg = {}  # aggregate class counts across all nodes

    for v in latest_readings.values():
        sd = v.get("sensor_data", {})
        t = sd.get("temperature")
        p = sd.get("ph")
        tb = sd.get("turbidity")
        if t is not None:
            temps.append(t)
        if p is not None:
            phs.append(p)
        if tb is not None:
            turbs.append(tb)
        trash_total += v.get("detection_result", {}).get("trash_count", 0)
        # Aggregate per-class detections
        cc = v.get("detection_result", {}).get("class_counts", {})
        for cls_name, cnt in cc.items():
            class_counts_agg[cls_name] = class_counts_agg.get(cls_name, 0) + cnt
        for k in anomaly_counts:
            if v.get("anomalies", {}).get(k):
                anomaly_counts[k] += 1
        # Collect rolling sensor stats from the anomaly detector
        node_stats = v.get("anomalies", {}).get("stats")
        if node_stats:
            sensor_stats = node_stats   # latest node's stats

    # Aggregate unknown object summaries across all nodes
    total_unknown_sightings = 0
    for v in latest_readings.values():
        us = v.get("detection_result", {}).get("unknown_summary", {})
        total_unknown_sightings += us.get("total_unknown_sightings", 0)

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
        "unknown_objects": {
            "total_sightings": total_unknown_sightings,
            "auto_labels_created": len(unknown_labels),
            "labels": list(unknown_labels.values()),
        },
    }


# ══════════════════════════════════════════════════════════════
#  REST API
# ══════════════════════════════════════════════════════════════

# ── Data submission (from Pi4 nodes) ─────────────────────────
@app.route("/api/data/submit", methods=["POST"])
def submit_data():
    d = request.json
    node_id = d.get("node_id", "unknown")
    log.info("Data received from %s  |  temp=%.1f  pH=%.2f  turb=%.0f  trash=%d",
             node_id,
             d.get("sensor_data", {}).get("temperature", 0),
             d.get("sensor_data", {}).get("ph", 0),
             d.get("sensor_data", {}).get("turbidity", 0),
             d.get("detection_result", {}).get("trash_count", 0))
    latest_readings[node_id] = {
        "sensor_data": d.get("sensor_data", {}),
        "detection_result": d.get("detection_result", {}),  # includes unknown_summary
        "anomalies": d.get("anomalies", {}),
        "timestamp": now_iso(),
    }
    trace("data_received", source=node_id,
          detail=f"temp={d.get('sensor_data', {}).get('temperature', 0):.1f} "
                 f"trash={d.get('detection_result', {}).get('trash_count', 0)}")

    # Store trash events with per-class breakdown
    tc = d.get("detection_result", {}).get("trash_count", 0)
    cc = d.get("detection_result", {}).get("class_counts", {})
    if tc > 0:
        trash_events.append({
            "node_id": node_id, "count": tc,
            "class_counts": cc, "timestamp": now_iso(),
        })
        if len(trash_events) > 500:
            trash_events[:] = trash_events[-500:]
        # Update running class totals
        for cls_name, cnt in cc.items():
            trash_class_totals[cls_name] = trash_class_totals.get(cls_name, 0) + cnt
        trace("trash_detected", source=node_id,
              detail=f"{tc} items — classes: {cc}")

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
    trace("node_registered", source=nid, detail=d.get("node_type", "unknown"))
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
    trace("federation_update", source=nid,
          detail=f"{len(weights)} weights — round {prev_round}→{fed_server.current_round}")
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
        "class_totals": trash_class_totals,
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "uptime": time.process_time()})


@app.route("/api/system/trace", methods=["GET"])
def get_trace():
    """Return the system event trace log for diagnostics."""
    limit = request.args.get("limit", 100, type=int)
    return jsonify({
        "trace": system_trace[-limit:],
        "total_events": len(system_trace),
    })


@app.route("/api/system/diagnostics", methods=["GET"])
def diagnostics():
    """Full system diagnostics — nodes, federation, data pipeline health."""
    active = 0
    stale = 0
    for n in nodes.values():
        elapsed = (datetime.utcnow() - datetime.fromisoformat(
            n["last_heartbeat"].rstrip("Z"))).total_seconds()
        if elapsed < 60:
            active += 1
        else:
            stale += 1

    return jsonify({
        "server": {
            "uptime_s": round(time.process_time(), 2),
            "nodes_registered": len(nodes),
            "nodes_active": active,
            "nodes_stale": stale,
        },
        "data_pipeline": {
            "total_readings": len(latest_readings),
            "total_trash_events": len(trash_events),
            "trash_class_totals": trash_class_totals,
            "total_alerts": len(alerts),
        },
        "federation": {
            "current_round": fed_server.current_round,
            "pending_updates": len(fed_server.updates),
            "has_global_model": fed_server.global_weights is not None,
        },
        "trace_log_size": len(system_trace),
        "timestamp": now_iso(),
    })


# ── Unknown Object Discovery ─────────────────────────────────
@app.route("/api/discovery/new_label", methods=["POST"])
def new_label():
    """
    Receive a newly discovered unknown waste label from an edge node.
    Aggregates sightings across zones — if multiple nodes see the same
    cluster, sighting counts are summed. An alert is raised on first discovery.
    """
    d = request.json
    label        = d.get("label")
    node_id      = d.get("node_id", "unknown")
    cluster_id   = d.get("cluster_id", "auto")
    sighting_count = int(d.get("sighting_count", 1))
    timestamp    = d.get("timestamp", time.time())

    if not label:
        return jsonify({"error": "missing label"}), 400

    is_new = label not in unknown_labels
    if is_new:
        unknown_labels[label] = {
            "label":          label,
            "cluster_id":     cluster_id,
            "sighting_count": sighting_count,
            "first_seen":     now_iso(),
            "last_seen":      now_iso(),
            "zones":          [node_id],
        }
        # Raise a dashboard alert for the new discovery
        alerts.append({
            "message":   f"New waste category auto-discovered: '{label}' at {node_id}",
            "severity":  "info",
            "type":      "unknown_object",
            "node_id":   node_id,
            "label":     label,
            "timestamp": now_iso(),
        })
        if len(alerts) > 200:
            alerts[:] = alerts[-200:]
        log.info("🆕 New unknown label registered: %s from %s (%d sightings)",
                 label, node_id, sighting_count)
    else:
        # Update existing entry — accumulate sightings, track all reporting zones
        entry = unknown_labels[label]
        entry["sighting_count"] += sighting_count
        entry["last_seen"] = now_iso()
        if node_id not in entry["zones"]:
            entry["zones"].append(node_id)
        log.info("🔄 Unknown label '%s' updated: total sightings=%d, zones=%s",
                 label, entry["sighting_count"], entry["zones"])

    trace("unknown_label_discovered" if is_new else "unknown_label_updated",
          source=node_id, detail=f"label={label} sightings={sighting_count}")

    return jsonify({
        "status":  "created" if is_new else "updated",
        "label":   label,
        "total_sightings": unknown_labels[label]["sighting_count"],
    })


@app.route("/api/discovery/unknown_labels", methods=["GET"])
def get_unknown_labels():
    """Return all auto-discovered unknown waste labels."""
    return jsonify({
        "unknown_labels": list(unknown_labels.values()),
        "total":          len(unknown_labels),
    })


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
            "trash_class_totals": trash_class_totals,
            "unknown_labels": list(unknown_labels.values()),
        }
        socketio.emit("river_update", payload)


# ── Start ────────────────────────────────────────────────────
# ── Configuration ────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"   # listen on all interfaces
SERVER_PORT = 5000         # ← must match PI5_PORT in pi4_edge_node/config.py

if __name__ == "__main__":
    log.info("=== Pi5 Central Server starting ===")
    log.info("BUILD_DIR = %s (exists: %s)", BUILD_DIR, os.path.isdir(BUILD_DIR))
    log.info("Listening on http://%s:%d", SERVER_HOST, SERVER_PORT)
    socketio.start_background_task(broadcast_loop)
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=False)
