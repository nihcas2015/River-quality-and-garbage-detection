#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Headless Raspberry Pi Setup — RustDesk + VNC + SSH
# ═══════════════════════════════════════════════════════════════
# Run this script ONCE on each Pi while a monitor is connected.
# After reboot, you can access the Pi from your laptop without
# any monitor — RustDesk auto-starts and is always reachable.
#
# Usage:
#   chmod +x setup_headless_pi.sh
#   sudo ./setup_headless_pi.sh
# ═══════════════════════════════════════════════════════════════

set -e

echo "========================================"
echo " Headless Raspberry Pi Setup"
echo "========================================"

# ── 1. System update ────────────────────────────────────────
echo "[1/6] Updating system packages..."
apt-get update && apt-get upgrade -y

# ── 2. Enable SSH (always on) ──────────────────────────────
echo "[2/6] Enabling SSH server..."
systemctl enable ssh
systemctl start ssh
echo "  ✓ SSH enabled — connect from laptop: ssh pi@$(hostname -I | awk '{print $1}')"

# ── 3. Enable VNC (backup remote access) ───────────────────
echo "[3/6] Enabling VNC server..."
apt-get install -y realvnc-vnc-server realvnc-vnc-viewer 2>/dev/null || true
raspi-config nonint do_vnc 0
systemctl enable vncserver-x11-serviced 2>/dev/null || true
echo "  ✓ VNC enabled on port 5900"

# ── 4. Install RustDesk (auto-start, works like AnyDesk) ───
echo "[4/6] Installing RustDesk..."
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    RUSTDESK_DEB="rustdesk-1.3.7-aarch64.deb"
    RUSTDESK_URL="https://github.com/rustdesk/rustdesk/releases/download/1.3.7/${RUSTDESK_DEB}"
elif [ "$ARCH" = "armv7l" ]; then
    RUSTDESK_DEB="rustdesk-1.3.7-armhf.deb"
    RUSTDESK_URL="https://github.com/rustdesk/rustdesk/releases/download/1.3.7/${RUSTDESK_DEB}"
else
    echo "  ⚠ Unknown arch: $ARCH — skipping RustDesk (install manually)"
    RUSTDESK_URL=""
fi

if [ -n "$RUSTDESK_URL" ]; then
    cd /tmp
    wget -q "$RUSTDESK_URL" -O rustdesk.deb 2>/dev/null || \
        curl -sLo rustdesk.deb "$RUSTDESK_URL"
    dpkg -i rustdesk.deb || apt-get install -f -y
    rm -f rustdesk.deb
    
    # Enable RustDesk service (auto-start on boot)
    systemctl enable rustdesk
    systemctl start rustdesk
    echo "  ✓ RustDesk installed and auto-starts on boot"
    echo "  ✓ Get your RustDesk ID: rustdesk --get-id"
fi

# ── 5. Set static-ish hostname for easy discovery ──────────
echo "[5/6] Configuring network..."
PI_IP=$(hostname -I | awk '{print $1}')
echo "  Current IP: $PI_IP"
echo "  Hostname:   $(hostname)"

# Enable mDNS so you can reach it as <hostname>.local
apt-get install -y avahi-daemon 2>/dev/null || true
systemctl enable avahi-daemon
echo "  ✓ mDNS enabled — reach this Pi as $(hostname).local"

# ── 6. Auto-login to desktop (needed for RustDesk GUI) ─────
echo "[6/6] Configuring auto-login to desktop..."
raspi-config nonint do_boot_behaviour B4 2>/dev/null || true
echo "  ✓ Desktop auto-login enabled"

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================"
echo " Setup Complete!"
echo "========================================"
echo ""
echo " Access methods (no monitor needed after reboot):"
echo ""
echo "  1. RustDesk (recommended — works like AnyDesk):"
echo "     - Install RustDesk on your laptop: https://rustdesk.com"
echo "     - Get this Pi's ID: rustdesk --get-id"
echo "     - Connect from laptop using that ID"
echo "     - Auto-starts on every boot ✓"
echo ""
echo "  2. SSH (terminal only):"
echo "     ssh pi@$PI_IP"
echo "     ssh pi@$(hostname).local"
echo ""
echo "  3. VNC (graphical, backup):"
echo "     Connect to $PI_IP:5900"
echo ""
echo " Reboot now? (y/n)"
read -r answer
if [ "$answer" = "y" ]; then
    reboot
fi
