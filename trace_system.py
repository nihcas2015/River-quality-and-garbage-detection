#!/usr/bin/env python3
"""
System Trace & Verification Script
═══════════════════════════════════
Run this from your laptop to verify the entire pipeline:
  ESP32 → Pi4 (MQTT + YOLO) → Pi5 (Server + Fed.) → Dashboard

Usage:
  python trace_system.py --pi5 192.168.1.100 --pi4 192.168.1.101

Or just:
  python trace_system.py --pi5 192.168.1.100
"""

import argparse
import json
import sys
import time
import subprocess

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# ── ANSI colors ──────────────────────────────────────────────
G = "\033[92m"   # green
R = "\033[91m"   # red
Y = "\033[93m"   # yellow
B = "\033[94m"   # blue
W = "\033[0m"    # reset
BOLD = "\033[1m"


def ok(msg):
    print(f"  {G}✓{W} {msg}")


def fail(msg):
    print(f"  {R}✗{W} {msg}")


def warn(msg):
    print(f"  {Y}⚠{W} {msg}")


def header(msg):
    print(f"\n{BOLD}{B}{'═' * 56}{W}")
    print(f"{BOLD}{B}  {msg}{W}")
    print(f"{BOLD}{B}{'═' * 56}{W}")


def check_ping(ip, label):
    """Check if a host is reachable."""
    try:
        # Windows: -n, Linux/Mac: -c
        flag = "-n" if sys.platform == "win32" else "-c"
        result = subprocess.run(
            ["ping", flag, "1", "-w", "2000" if sys.platform == "win32" else "2", ip],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            ok(f"{label} ({ip}) — reachable")
            return True
        else:
            fail(f"{label} ({ip}) — not reachable")
            return False
    except Exception as e:
        fail(f"{label} ({ip}) — ping error: {e}")
        return False


def check_api(base_url, endpoint, label):
    """Make a GET request and check the response."""
    url = f"{base_url}{endpoint}"
    try:
        r = requests.get(url, timeout=5)
        if r.ok:
            ok(f"{label} — {url} → {r.status_code}")
            return r.json()
        else:
            fail(f"{label} — {url} → {r.status_code}")
            return None
    except requests.ConnectionError:
        fail(f"{label} — {url} → connection refused")
        return None
    except Exception as e:
        fail(f"{label} — {url} → {e}")
        return None


def check_mqtt(pi4_ip):
    """Test MQTT connectivity to Pi4 broker."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((pi4_ip, 1883))
        s.close()
        ok(f"MQTT broker ({pi4_ip}:1883) — port open")
        return True
    except Exception as e:
        fail(f"MQTT broker ({pi4_ip}:1883) — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Trace & verify River Monitoring System")
    parser.add_argument("--pi5", required=True, help="Pi5 IP address")
    parser.add_argument("--pi4", default=None, help="Pi4 IP address (optional)")
    parser.add_argument("--port", type=int, default=5000, help="Pi5 server port (default: 5000)")
    args = parser.parse_args()

    base = f"http://{args.pi5}:{args.port}"
    results = {"pass": 0, "fail": 0, "warn": 0}

    # ── 1. Network connectivity ─────────────────────────────
    header("1. Network Connectivity")
    if check_ping(args.pi5, "Pi5 Central Server"):
        results["pass"] += 1
    else:
        results["fail"] += 1

    if args.pi4:
        if check_ping(args.pi4, "Pi4 Edge Node"):
            results["pass"] += 1
        else:
            results["fail"] += 1

        if check_mqtt(args.pi4):
            results["pass"] += 1
        else:
            results["fail"] += 1

    # ── 2. Pi5 Server health ────────────────────────────────
    header("2. Pi5 Server Health")
    health = check_api(base, "/api/health", "Health endpoint")
    if health:
        results["pass"] += 1
        ok(f"Uptime: {health.get('uptime', '?')}s")
    else:
        results["fail"] += 1

    # ── 3. Data pipeline ────────────────────────────────────
    header("3. Data Pipeline")
    river = check_api(base, "/api/dashboard/river_data", "River data")
    if river:
        results["pass"] += 1
        print(f"      Avg temp:     {river.get('avg_temperature', 0):.1f}°C")
        print(f"      Avg pH:       {river.get('avg_ph', 0):.2f}")
        print(f"      Avg turbidity:{river.get('avg_turbidity', 0):.1f} NTU")
        print(f"      Total trash:  {river.get('total_trash_detected', 0)}")
        print(f"      Node count:   {river.get('node_count', 0)}")

        # Class breakdown
        cc = river.get("trash_class_counts", {})
        ct = river.get("trash_class_totals", {})
        if ct:
            ok(f"Trash class totals (historical): {json.dumps(ct)}")
        elif cc:
            ok(f"Trash class counts (current): {json.dumps(cc)}")
        else:
            warn("No trash class data yet (no detections)")
            results["warn"] += 1
    else:
        results["fail"] += 1

    # ── 4. Federation status ────────────────────────────────
    header("4. Federation Status")
    fed = check_api(base, "/api/federation/status", "Federation status")
    if fed:
        results["pass"] += 1
        print(f"      Total nodes:  {fed.get('total_nodes', 0)}")
        print(f"      Active nodes: {fed.get('active_nodes', 0)}")
        print(f"      Global round: {fed.get('global_round', 0)}")
        if fed.get("nodes"):
            for n in fed["nodes"]:
                status = "ACTIVE" if n.get("last_heartbeat") else "UNKNOWN"
                print(f"        → {n['node_id']} ({n.get('node_type', '?')}) — {status}")
        if fed.get("active_nodes", 0) == 0:
            warn("No active nodes — Pi4 may not be running")
            results["warn"] += 1
    else:
        results["fail"] += 1

    # ── 5. Alerts ───────────────────────────────────────────
    header("5. Alerts")
    alerts_data = check_api(base, "/api/dashboard/alerts", "Alerts endpoint")
    if alerts_data:
        results["pass"] += 1
        alert_list = alerts_data.get("alerts", [])
        print(f"      Total alerts: {len(alert_list)}")
        if alert_list:
            for a in alert_list[-3:]:
                sev = a.get("severity", "?").upper()
                print(f"        [{sev}] {a.get('message', '?')} — {a.get('timestamp', '')}")
    else:
        results["fail"] += 1

    # ── 6. Trash history ────────────────────────────────────
    header("6. Trash Detection History")
    trash = check_api(base, "/api/dashboard/trash_history?limit=10", "Trash history")
    if trash:
        results["pass"] += 1
        events = trash.get("trash_events", [])
        ct = trash.get("class_totals", {})
        print(f"      Total detections: {trash.get('total_count', 0)}")
        print(f"      Recent events:    {len(events)}")
        if ct:
            print(f"      Class totals:     {json.dumps(ct)}")
        if events:
            for e in events[-3:]:
                cc = e.get("class_counts", {})
                cc_str = ", ".join(f"{k}:{v}" for k, v in cc.items()) if cc else "no class data"
                print(f"        → {e['node_id']}: {e['count']} items [{cc_str}] @ {e.get('timestamp', '')}")
    else:
        results["fail"] += 1

    # ── 7. System diagnostics ───────────────────────────────
    header("7. System Diagnostics")
    diag = check_api(base, "/api/system/diagnostics", "Diagnostics")
    if diag:
        results["pass"] += 1
        srv = diag.get("server", {})
        pipe = diag.get("data_pipeline", {})
        fed_d = diag.get("federation", {})
        print(f"      Uptime:          {srv.get('uptime_s', '?')}s")
        print(f"      Registered:      {srv.get('nodes_registered', 0)} nodes")
        print(f"      Active:          {srv.get('nodes_active', 0)} nodes")
        print(f"      Stale:           {srv.get('nodes_stale', 0)} nodes")
        print(f"      Readings:        {pipe.get('total_readings', 0)}")
        print(f"      Trash events:    {pipe.get('total_trash_events', 0)}")
        print(f"      Alerts:          {pipe.get('total_alerts', 0)}")
        print(f"      Fed. round:      {fed_d.get('current_round', 0)}")
        print(f"      Global model:    {'yes' if fed_d.get('has_global_model') else 'no'}")
    else:
        results["fail"] += 1

    # ── 8. System trace log ─────────────────────────────────
    header("8. System Trace Log")
    trace = check_api(base, "/api/system/trace?limit=10", "Trace log")
    if trace:
        results["pass"] += 1
        entries = trace.get("trace", [])
        print(f"      Total events: {trace.get('total_events', 0)}")
        if entries:
            for t in entries[-5:]:
                print(f"        [{t.get('event', '?')}] {t.get('source', '?')} — "
                      f"{t.get('detail', '')[:60]} @ {t.get('timestamp', '')}")
        else:
            warn("No trace events yet (system may have just started)")
            results["warn"] += 1
    else:
        results["fail"] += 1

    # ── Summary ─────────────────────────────────────────────
    header("TRACE SUMMARY")
    total = results["pass"] + results["fail"] + results["warn"]
    print(f"  {G}PASS: {results['pass']}{W}  |  "
          f"{R}FAIL: {results['fail']}{W}  |  "
          f"{Y}WARN: {results['warn']}{W}  |  "
          f"Total: {total}")
    print()

    if results["fail"] == 0:
        print(f"  {G}{BOLD}All checks passed! System is operational.{W}")
    elif results["fail"] <= 2:
        print(f"  {Y}{BOLD}Some issues detected — check the failures above.{W}")
    else:
        print(f"  {R}{BOLD}Multiple failures — system may not be running correctly.{W}")

    print()
    print("  Port Reference:")
    print(f"    Pi5 Server:    http://{args.pi5}:{args.port}")
    print(f"    Dashboard:     http://{args.pi5}:{args.port}")
    if args.pi4:
        print(f"    Pi4 MQTT:      {args.pi4}:1883")
    print(f"    ESP32 → Pi4:   MQTT port 1883")
    print()

    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
