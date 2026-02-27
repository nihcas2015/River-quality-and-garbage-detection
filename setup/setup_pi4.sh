#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Pi4 Edge Node — One-shot setup & auto-start
# ═══════════════════════════════════════════════════════════════
# Run on Pi4 after headless setup. Installs dependencies,
# MQTT broker, and creates systemd services.
#
# Usage:
#   chmod +x setup_pi4.sh
#   sudo ./setup_pi4.sh
# ═══════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PI4_DIR="$PROJECT_DIR/pi4_edge_node"
USER_NAME="${SUDO_USER:-pi}"

echo "========================================"
echo " Pi4 Edge Node Setup"
echo "========================================"
echo " Project: $PROJECT_DIR"

# ── 1. Install Mosquitto MQTT broker ────────────────────────
echo "[1/4] Installing Mosquitto MQTT broker..."
apt-get update
apt-get install -y mosquitto mosquitto-clients
# Allow anonymous local connections (ESP32 doesn't auth by default)
cat > /etc/mosquitto/conf.d/river.conf << 'EOF'
listener 1883
allow_anonymous true
EOF
systemctl enable mosquitto
systemctl restart mosquitto
echo "  ✓ Mosquitto running on port 1883"

# ── 2. Python dependencies ──────────────────────────────────
echo "[2/4] Installing Python dependencies..."
apt-get install -y python3-pip python3-venv libcamera-apps
cd "$PI4_DIR"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
echo "  ✓ Python venv ready"

# ── 3. Enable camera ────────────────────────────────────────
echo "[3/4] Enabling Pi Camera..."
raspi-config nonint do_camera 0 2>/dev/null || true
# On Bookworm, camera is enabled by default via libcamera
echo "  ✓ Camera enabled (libcamera-still)"

# ── 4. Create systemd service ───────────────────────────────
echo "[4/4] Creating systemd service..."
cat > /etc/systemd/system/river-edge.service << EOF
[Unit]
Description=River Monitoring Edge Node (Pi4)
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PI4_DIR
ExecStart=$PI4_DIR/venv/bin/python main_edge.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable river-edge
systemctl start river-edge
echo "  ✓ Service created and started"

# ── Show status ─────────────────────────────────────────────
sleep 2
systemctl status river-edge --no-pager || true

PI4_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo " Pi4 Setup Complete!"
echo "========================================"
echo " Edge node running at: $PI4_IP"
echo " MQTT broker:          $PI4_IP:1883"
echo " Service name:         river-edge"
echo ""
echo " IMPORTANT: Update ESP32 code with:"
echo "   MQTT_SERVER = \"$PI4_IP\""
echo ""
echo " IMPORTANT: Update pi4_edge_node/config.py with:"
echo "   PI5_IP = \"<your Pi5 IP>\""
echo "   PI4_IP = \"$PI4_IP\""
echo ""
echo " Manage:"
echo "   sudo systemctl status river-edge"
echo "   sudo systemctl restart river-edge"
echo "   sudo journalctl -u river-edge -f"
echo "========================================"
