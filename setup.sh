#!/bin/bash
# =============================================================================
# Timelapse Camera - Initial Setup Script
# Run once on first boot to configure WiFi and enable SSH.
# Must be run as root: sudo bash setup.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}This script must be run as root (sudo bash setup.sh)${NC}"
    exit 1
fi

echo -e "${CYAN}"
echo "  ████████╗██╗███╗   ███╗███████╗██╗      █████╗ ██████╗ ███████╗███████╗"
echo "  ╚══██╔══╝██║████╗ ████║██╔════╝██║     ██╔══██╗██╔══██╗██╔════╝██╔════╝"
echo "     ██║   ██║██╔████╔██║█████╗  ██║     ███████║██████╔╝███████╗█████╗  "
echo "     ██║   ██║██║╚██╔╝██║██╔══╝  ██║     ██╔══██║██╔═══╝ ╚════██║██╔══╝  "
echo "     ██║   ██║██║ ╚═╝ ██║███████╗███████╗██║  ██║██║     ███████║███████╗"
echo "     ╚═╝   ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝     ╚══════╝╚══════╝"
echo -e "${NC}"
echo -e "${GREEN}  Raspberry Pi Zero 2W Timelapse Camera — Initial Setup${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. WiFi Configuration
# ---------------------------------------------------------------------------
echo -e "${YELLOW}── WiFi Configuration ──────────────────────────────────────────────────${NC}"
echo ""

read -rp "  WiFi SSID: " WIFI_SSID
read -rsp "  WiFi Password: " WIFI_PASSWORD
echo ""
echo ""

# Detect if using NetworkManager (Bookworm+) or wpa_supplicant (Bullseye)
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    echo -e "  ${CYAN}Configuring WiFi via NetworkManager...${NC}"
    nmcli device wifi connect "$WIFI_SSID" password "$WIFI_PASSWORD" 2>/dev/null || {
        # Connection profile may already exist; update password
        nmcli connection modify "$WIFI_SSID" wifi-sec.psk "$WIFI_PASSWORD"
        nmcli connection up "$WIFI_SSID"
    }
    echo -e "  ${GREEN}WiFi profile saved.${NC}"
else
    echo -e "  ${CYAN}Configuring WiFi via wpa_supplicant...${NC}"
    WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"

    # Ensure country code is set (required for WiFi to be enabled)
    if ! grep -q "^country=" "$WPA_CONF" 2>/dev/null; then
        read -rp "  Country code (e.g. US, GB, CA): " COUNTRY
        cat >> "$WPA_CONF" <<EOF

country=${COUNTRY^^}
EOF
    fi

    PSK=$(wpa_passphrase "$WIFI_SSID" <<< "$WIFI_PASSWORD" | grep -v "#psk" | grep "psk=" | awk -F= '{print $2}')

    # Remove existing entry for this SSID if present
    python3 - "$WPA_CONF" "$WIFI_SSID" <<'PYEOF'
import sys, re
path, ssid = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
# Remove network block matching ssid
pattern = r'network=\{[^}]*ssid="' + re.escape(ssid) + r'"[^}]*\}\n?'
content = re.sub(pattern, '', content, flags=re.DOTALL)
with open(path, 'w') as f:
    f.write(content)
PYEOF

    cat >> "$WPA_CONF" <<EOF

network={
    ssid="$WIFI_SSID"
    psk=$PSK
    key_mgmt=WPA-PSK
}
EOF
    wpa_cli -i wlan0 reconfigure &>/dev/null || true
    echo -e "  ${GREEN}WiFi configuration written to ${WPA_CONF}.${NC}"
fi

# ---------------------------------------------------------------------------
# 2. Enable & Start SSH
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}── SSH Configuration ───────────────────────────────────────────────────${NC}"
echo ""

systemctl enable ssh
systemctl start ssh
echo -e "  ${GREEN}SSH enabled and running.${NC}"

HOSTNAME=$(hostname)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
ACTUAL_USER="${SUDO_USER:-$(logname)}"
echo -e "  Connect with: ${CYAN}ssh ${ACTUAL_USER}@${IP:-<ip-address>}${NC}  (hostname: ${HOSTNAME})"
echo ""

# ---------------------------------------------------------------------------
# 3. System dependencies
# ---------------------------------------------------------------------------
echo -e "${YELLOW}── Installing Dependencies ─────────────────────────────────────────────${NC}"
echo ""

apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-picamera2 \
    python3-pip \
    ffmpeg \
    libcamera-apps \
    2>&1 | grep -E "(Unpacking|Setting up|already)" || true

pip3 install --break-system-packages --quiet tqdm 2>/dev/null || \
pip3 install --quiet tqdm

echo -e "  ${GREEN}Dependencies installed.${NC}"
echo ""

# ---------------------------------------------------------------------------
# 4. Mark setup complete and create systemd service (optional auto-start)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
touch "$SCRIPT_DIR/.setup_complete"

read -rp "  Install timelapse as a systemd service for easy launch? [y/N] " INSTALL_SERVICE
if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
    ACTUAL_USER="${SUDO_USER:-$(logname)}"
    ACTUAL_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)
    cat > /etc/systemd/system/timelapse.service <<EOF
[Unit]
Description=Timelapse Camera Application
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/timelapse.py
StandardInput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
Restart=no

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    echo -e "  ${GREEN}Service installed. Start with: ${CYAN}sudo systemctl start timelapse${NC}"
fi

echo ""
echo -e "${GREEN}══ Setup complete! ════════════════════════════════════════════════════${NC}"
echo -e "  Run the timelapse app with: ${CYAN}python3 timelapse.py${NC}"
echo ""
