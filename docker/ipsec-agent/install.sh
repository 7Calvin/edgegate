#!/bin/bash
# Install StrongSwan and IPsec Agent on the host
# Run this script as root on the VPN server

set -e

INSTALL_DIR="/opt/edgegate/ipsec-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  StrongSwan + IPsec Agent Installer"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo ./install.sh)"
    exit 1
fi

# ==================== Install StrongSwan ====================
echo "=== Step 1: Installing StrongSwan ==="

if command -v ipsec &> /dev/null; then
    echo "StrongSwan already installed:"
    ipsec version | head -1
else
    echo "Installing StrongSwan..."
    apt-get update
    apt-get install -y strongswan strongswan-pki libcharon-extra-plugins
    echo "StrongSwan installed:"
    ipsec version | head -1
fi

# Ensure minimal ipsec.conf exists so StrongSwan can start
if [ ! -f /etc/ipsec.conf ]; then
    echo "Creating minimal /etc/ipsec.conf..."
    cat > /etc/ipsec.conf << 'IPSECCONF'
# ipsec.conf - StrongSwan IPsec configuration
# This file will be managed by EdgeGate
config setup
IPSECCONF
fi

if [ ! -f /etc/ipsec.secrets ]; then
    echo "Creating minimal /etc/ipsec.secrets..."
    touch /etc/ipsec.secrets
    chmod 600 /etc/ipsec.secrets
fi

# Enable StrongSwan service
systemctl enable strongswan-starter
systemctl start strongswan-starter || true
echo ""

# ==================== Install IPsec Agent ====================
echo "=== Step 2: Installing IPsec Agent ==="

# Create directory
mkdir -p "$INSTALL_DIR"

# Copy files
cp "$SCRIPT_DIR/app.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Check for Python3
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    apt-get install -y python3 python3-pip python3-venv
fi

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

# Install dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

deactivate
echo ""

# ==================== Generate Secure Token ====================
echo "=== Step 3: Configuring Authentication ==="

TOKEN_FILE="/opt/edgegate/ipsec-agent.token"
if [ ! -f "$TOKEN_FILE" ]; then
    echo "Generating secure token..."
    TOKEN=$(openssl rand -hex 32)
    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
else
    TOKEN=$(cat "$TOKEN_FILE")
    echo "Using existing token from $TOKEN_FILE"
fi
echo ""

# ==================== Install Systemd Service ====================
echo "=== Step 4: Installing Systemd Service ==="

cat > /etc/systemd/system/ipsec-agent.service << EOF
[Unit]
Description=IPsec Agent for EdgeGate
After=network.target strongswan-starter.service
Wants=strongswan-starter.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$INSTALL_DIR
Environment="IPSEC_AGENT_TOKEN=$TOKEN"
Environment="IPSEC_AGENT_PORT=8101"
ExecStart=$INSTALL_DIR/venv/bin/gunicorn -w 2 -b 0.0.0.0:8101 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload and start service
systemctl daemon-reload
systemctl enable ipsec-agent
systemctl restart ipsec-agent
echo ""

# ==================== Verification ====================
echo "=== Step 5: Verifying Installation ==="

sleep 2

echo "StrongSwan status:"
systemctl is-active strongswan-starter && echo "  ✓ StrongSwan is running" || echo "  ✗ StrongSwan not running"

echo "IPsec Agent status:"
systemctl is-active ipsec-agent && echo "  ✓ IPsec Agent is running" || echo "  ✗ IPsec Agent not running"

# Test agent health endpoint
echo ""
echo "Testing agent health endpoint..."
HEALTH=$(curl -s http://127.0.0.1:8101/health 2>/dev/null || echo "failed")
if echo "$HEALTH" | grep -q "healthy"; then
    echo "  ✓ Agent responding correctly"
else
    echo "  ✗ Agent health check failed: $HEALTH"
fi

echo ""
echo "========================================"
echo "        Installation Complete!"
echo "========================================"
echo ""
echo "IPsec Agent Token: $TOKEN"
echo ""
echo "Add these to your backend .env file:"
echo ""
echo "  IPSEC_AGENT_URL=http://172.17.0.1:8101"
echo "  IPSEC_AGENT_TOKEN=$TOKEN"
echo ""
echo "Note: 172.17.0.1 is the Docker host IP accessible from containers."
echo "      If using a different Docker network, adjust accordingly."
echo ""
echo "Commands:"
echo "  - Check status:   systemctl status ipsec-agent"
echo "  - View logs:      journalctl -u ipsec-agent -f"
echo "  - Restart:        systemctl restart ipsec-agent"
echo "  - StrongSwan:     ipsec statusall"
echo ""
