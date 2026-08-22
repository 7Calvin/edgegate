#!/bin/bash
# Fix permissions for EdgeGate - Production Version

set -e

echo "========================================="
echo "  EdgeGate - Fix Script"
echo "========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Must run as root
if [ "$EUID" -ne 0 ]; then
   echo -e "${RED}Please run as root (sudo)${NC}"
   exit 1
fi

# 1. Fix /app/data permissions via root inside container
echo -e "\n${YELLOW}1. Fixing /app/data permissions...${NC}"
docker exec -u root edgegate-backend chown -R vpnuser:vpnuser /app/data
docker exec -u root edgegate-backend chmod -R 755 /app/data
echo -e "${GREEN}✓ Permissions fixed${NC}"

# 2. Alternatively, fix the volume directly on host
echo -e "\n${YELLOW}2. Fixing volume permissions on host...${NC}"
VOLUME_PATH=$(docker volume inspect edgegate_backend_data --format '{{ .Mountpoint }}')
if [ -d "$VOLUME_PATH" ]; then
    chown -R 1000:1000 "$VOLUME_PATH"
    chmod -R 755 "$VOLUME_PATH"
    echo -e "${GREEN}✓ Volume permissions fixed: $VOLUME_PATH${NC}"
else
    echo -e "${YELLOW}⚠ Volume path not found: $VOLUME_PATH${NC}"
fi

# 3. Check docker.sock mount
echo -e "\n${YELLOW}3. Checking docker.sock mount...${NC}"
if docker exec edgegate-backend test -S /var/run/docker.sock; then
    echo -e "${GREEN}✓ Docker socket is accessible${NC}"
    docker exec edgegate-backend ls -la /var/run/docker.sock
else
    echo -e "${RED}✗ Docker socket NOT accessible${NC}"
    echo "Fixing docker.sock permissions..."

    # Make sure docker.sock has correct permissions on host
    chmod 666 /var/run/docker.sock

    # Recreate backend container with correct mount
    echo -e "${YELLOW}Recreating backend container...${NC}"
    cd /opt/edgegate
    docker compose up -d backend --force-recreate
    echo -e "${GREEN}✓ Container recreated${NC}"

    # Wait for container to be ready
    sleep 5
fi

# 4. Set up OpenVPN status file access
echo -e "\n${YELLOW}4. Setting up OpenVPN status file access...${NC}"
docker exec edgegate-openvpn chmod 644 /etc/openvpn/logs/status.log 2>/dev/null || true
echo -e "${GREEN}✓ Status file permissions set${NC}"

# 5. Verify backend user can write to data directory
echo -e "\n${YELLOW}5. Testing write permissions...${NC}"
if docker exec -u vpnuser edgegate-backend touch /app/data/test.txt 2>/dev/null; then
    docker exec edgegate-backend rm /app/data/test.txt
    echo -e "${GREEN}✓ Backend user can write to /app/data${NC}"
else
    echo -e "${RED}✗ Backend user CANNOT write to /app/data${NC}"
    echo "Trying alternative fix..."
    docker exec -u root edgegate-backend chown -R 1000:1000 /app/data
fi

# 6. Restart backend to apply changes
echo -e "\n${YELLOW}6. Restarting backend...${NC}"
cd /opt/edgegate
docker compose restart backend
echo -e "${GREEN}✓ Backend restarted${NC}"

# 7. Wait for backend to be healthy
echo -e "\n${YELLOW}7. Waiting for backend to be healthy...${NC}"
for i in {1..30}; do
    if docker inspect edgegate-backend 2>/dev/null | grep -q '"Status": "healthy"'; then
        echo -e "${GREEN}✓ Backend is healthy${NC}"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# 8. Test API
echo -e "\n${YELLOW}8. Testing API...${NC}"
if curl -f -s http://localhost/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API is responding${NC}"
else
    echo -e "${RED}✗ API is not responding${NC}"
    echo "Check logs with: docker compose logs backend"
fi

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}  Fix script completed!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Try saving VPN configuration again"
echo "  2. Try starting OpenVPN server"
echo ""
echo "If issues persist:"
echo "  - Check logs: docker compose logs -f backend"
echo "  - Verify permissions: docker exec -u vpnuser edgegate-backend ls -la /app/data"
echo "  - Check docker socket: docker exec edgegate-backend ls -la /var/run/docker.sock"
