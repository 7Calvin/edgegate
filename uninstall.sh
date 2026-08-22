#!/bin/bash
#
# EdgeGate - Uninstall/Cleanup Script
# Removes all containers, volumes, images and installation files
#
# Usage: sudo ./uninstall.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/opt/edgegate"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║       EdgeGate - Uninstall/Cleanup           ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} This script must be run as root"
    echo "Please run: sudo $0"
    exit 1
fi

echo -e "${YELLOW}WARNING: This will remove ALL EdgeGate data!${NC}"
echo ""
echo "This includes:"
echo "  - All IPsec tunnels and StrongSwan configurations"
echo "  - IPsec Agent service"
echo "  - All Docker containers (edgegate-backend, edgegate-frontend, edgegate-openvpn, etc.)"
echo "  - All Docker volumes (database, redis, openvpn data)"
echo "  - All Docker images built for this project"
echo "  - Installation directory: ${INSTALL_DIR}"
echo ""
read -p "Are you sure you want to continue? [y/N]: " confirm

if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${CYAN}Starting cleanup...${NC}"

# Stop IPsec tunnels and services
echo -e "${YELLOW}[1/7]${NC} Stopping IPsec tunnels and StrongSwan..."
if command -v ipsec &> /dev/null; then
    # Stop all IPsec connections
    ipsec down --all 2>/dev/null || true
    ipsec stop 2>/dev/null || true
fi

# Stop and disable IPsec Agent
if systemctl is-active --quiet ipsec-agent 2>/dev/null; then
    echo "  Stopping IPsec Agent..."
    systemctl stop ipsec-agent 2>/dev/null || true
fi
systemctl disable ipsec-agent 2>/dev/null || true
rm -f /etc/systemd/system/ipsec-agent.service
systemctl daemon-reload 2>/dev/null || true

# Remove IPsec Agent files
if [ -d "/opt/edgegate/ipsec-agent" ]; then
    echo "  Removing IPsec Agent..."
    rm -rf /opt/edgegate/ipsec-agent
    rm -f /opt/edgegate/ipsec-agent.token
fi

# Clean StrongSwan configs (but keep StrongSwan installed)
echo -e "${YELLOW}[2/7]${NC} Cleaning IPsec configurations..."
rm -f /etc/ipsec.conf 2>/dev/null || true
rm -f /etc/ipsec.secrets 2>/dev/null || true
rm -rf /etc/ipsec.d/*.conf 2>/dev/null || true

# Stop and remove containers
if [ -d "${INSTALL_DIR}" ]; then
    echo -e "${YELLOW}[3/7]${NC} Stopping containers..."
    cd ${INSTALL_DIR}
    docker compose down -v 2>/dev/null || true
fi

# Remove project containers (in case compose didn't get them)
echo -e "${YELLOW}[4/7]${NC} Removing project containers..."
docker ps -a --filter "name=vpn-" -q | xargs -r docker rm -f 2>/dev/null || true

# Remove project images
echo -e "${YELLOW}[5/7]${NC} Removing project images..."
docker images --filter "reference=edgegate*" -q | xargs -r docker rmi -f 2>/dev/null || true
docker images --filter "reference=*edgegate*" -q | xargs -r docker rmi -f 2>/dev/null || true

# Prune unused resources
echo -e "${YELLOW}[6/7]${NC} Pruning unused Docker resources..."
docker system prune -af 2>/dev/null || true

# Remove installation directory
echo -e "${YELLOW}[7/7]${NC} Removing installation directory..."
rm -rf ${INSTALL_DIR}

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}║              Cleanup Complete!                            ║${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "You can now run ./install.sh to reinstall."
echo ""
