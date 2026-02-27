#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Pi5 Central Node — One-shot setup & auto-start
# ═══════════════════════════════════════════════════════════════
# Run on Pi5 after headless setup. Installs dependencies,
# builds the dashboard, and creates a systemd service that
# starts the server automatically on every boot.
#
# Usage:
#   chmod +x setup_pi5.sh
#   sudo ./setup_pi5.sh
# ═══════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PI5_DIR="$PROJECT_DIR/pi5_central_node"
DASH_DIR="$PROJECT_DIR/dashboard/frontend"
USER_NAME="${SUDO_USER:-pi}"

echo "========================================"
echo " Pi5 Central Server Setup"
echo "========================================"
echo " Project: $PROJECT_DIR"

# ── 1. Python dependencies ──────────────────────────────────
echo "[1/4] Installing Python dependencies..."
apt-get install -y python3-pip python3-venv
cd "$PI5_DIR"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# ── 2. Build React dashboard ────────────────────────────────
echo "[2/4] Building dashboard..."
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi
cd "$DASH_DIR"
npm install
npm run build
echo "  ✓ Dashboard built at $DASH_DIR/build"

# ── 3. Create systemd service ───────────────────────────────
echo "[3/4] Creating systemd service..."
cat > /etc/systemd/system/river-server.service << EOF
[Unit]
Description=River Monitoring Central Server (Pi5)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PI5_DIR
ExecStart=$PI5_DIR/venv/bin/python server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable river-server
systemctl start river-server
echo "  ✓ Service created and started"

# ── 4. Show status ──────────────────────────────────────────
echo "[4/4] Verifying..."
sleep 2
systemctl status river-server --no-pager || true

PI5_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo " Pi5 Setup Complete!"
echo "========================================"
echo " Server running at: http://$PI5_IP:5000"
echo " Dashboard URL:     http://$PI5_IP:5000"
echo " Service name:      river-server"
echo ""
echo " Manage:"
echo "   sudo systemctl status river-server"
echo "   sudo systemctl restart river-server"
echo "   sudo journalctl -u river-server -f"
echo "========================================"
