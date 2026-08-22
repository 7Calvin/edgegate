#!/bin/bash
# Fix permissions for EdgeGate in production

set -e

echo "========================================="
echo "  EdgeGate - Fix Script"
echo "========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Fix /app/data permissions
echo -e "\n${YELLOW}1. Fixing /app/data permissions...${NC}"
sudo docker exec edgegate-backend chown -R vpnuser:vpnuser /app/data
sudo docker exec edgegate-backend chmod -R 755 /app/data
echo -e "${GREEN}✓ Permissions fixed${NC}"

# 2. Check docker.sock mount
echo -e "\n${YELLOW}2. Checking docker.sock mount...${NC}"
if sudo docker exec edgegate-backend test -S /var/run/docker.sock; then
    echo -e "${GREEN}✓ Docker socket is accessible${NC}"
    sudo docker exec edgegate-backend ls -la /var/run/docker.sock
else
    echo -e "${RED}✗ Docker socket NOT accessible${NC}"
    echo "Checking if docker.sock exists on host..."
    if [ -S /var/run/docker.sock ]; then
        echo -e "${GREEN}✓ Docker socket exists on host${NC}"
        echo -e "${YELLOW}Recreating backend container with correct mount...${NC}"
        cd /opt/edgegate
        sudo docker compose up -d backend --force-recreate
        echo -e "${GREEN}✓ Container recreated${NC}"
    else
        echo -e "${RED}✗ Docker socket does not exist on host${NC}"
        echo "Please check your Docker installation"
        exit 1
    fi
fi

# 3. Create status log volume mount if needed
echo -e "\n${YELLOW}3. Setting up OpenVPN status file access...${NC}"
sudo docker exec edgegate-openvpn chmod 644 /etc/openvpn/logs/status.log 2>/dev/null || true
echo -e "${GREEN}✓ Status file permissions set${NC}"

# 4. Restart backend to apply changes
echo -e "\n${YELLOW}4. Restarting backend...${NC}"
cd /opt/edgegate
sudo docker compose restart backend
echo -e "${GREEN}✓ Backend restarted${NC}"

# 5. Wait for backend to be healthy
echo -e "\n${YELLOW}5. Waiting for backend to be healthy...${NC}"
for i in {1..30}; do
    if sudo docker inspect edgegate-backend | grep -q '"Health":.*"healthy"'; then
        echo -e "${GREEN}✓ Backend is healthy${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}  Fix script completed!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "You can now try:"
echo "  1. Save VPN configuration"
echo "  2. Start/Stop OpenVPN server"
echo ""
echo "Check logs with: sudo docker compose logs -f backend"
