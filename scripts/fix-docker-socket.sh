#!/bin/bash
# Fix docker.sock mount for EdgeGate Backend

set -e

echo "========================================="
echo "  Docker Socket Fix Script"
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

# 1. Check if docker.sock exists on host
echo -e "\n${YELLOW}1. Checking docker.sock on host...${NC}"
if [ ! -S /var/run/docker.sock ]; then
    echo -e "${RED}✗ Docker socket does NOT exist on host!${NC}"
    echo "Is Docker running?"
    systemctl status docker --no-pager
    exit 1
fi
echo -e "${GREEN}✓ Docker socket exists on host${NC}"
ls -la /var/run/docker.sock

# 2. Set correct permissions on host
# Restrict to the docker group (660) instead of world-writable (666). 666 makes
# the root-equivalent Docker socket usable by ANY local user = host root for
# everyone. The backend keeps access via `group_add: ${DOCKER_GID}` in compose.
echo -e "\n${YELLOW}2. Restricting docker.sock permissions (docker group, 660)...${NC}"
if getent group docker >/dev/null 2>&1; then
    chgrp docker /var/run/docker.sock 2>/dev/null || true
fi
chmod 660 /var/run/docker.sock
echo -e "${GREEN}✓ Permissions set to 660 (root:docker)${NC}"
ls -la /var/run/docker.sock

# 3. Check if backend container exists
echo -e "\n${YELLOW}3. Checking backend container...${NC}"
if ! docker ps -a --filter "name=edgegate-backend" --format "{{.Names}}" | grep -q "edgegate-backend"; then
    echo -e "${RED}✗ Backend container not found!${NC}"
    echo "Please run: docker compose up -d"
    exit 1
fi
echo -e "${GREEN}✓ Backend container exists${NC}"

# 4. Stop and remove backend container
echo -e "\n${YELLOW}4. Stopping backend container...${NC}"
cd /opt/edgegate
docker compose stop backend
docker compose rm -f backend
echo -e "${GREEN}✓ Backend container stopped and removed${NC}"

# 5. Recreate backend with correct mount
echo -e "\n${YELLOW}5. Recreating backend container...${NC}"
docker compose up -d backend
echo -e "${GREEN}✓ Backend container recreated${NC}"

# 6. Wait for container to start
echo -e "\n${YELLOW}6. Waiting for backend to start...${NC}"
for i in {1..30}; do
    if docker ps --filter "name=edgegate-backend" --format "{{.Names}}" | grep -q "edgegate-backend"; then
        echo -e "${GREEN}✓ Backend is running${NC}"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# 7. Verify docker.sock is accessible inside container
echo -e "\n${YELLOW}7. Verifying docker.sock inside container...${NC}"
if docker exec edgegate-backend test -S /var/run/docker.sock; then
    echo -e "${GREEN}✓ Docker socket IS accessible inside container${NC}"
    docker exec edgegate-backend ls -la /var/run/docker.sock
else
    echo -e "${RED}✗ Docker socket is NOT accessible inside container${NC}"
    echo ""
    echo "Checking docker-compose.yml configuration..."
    grep -A 5 "volumes:" docker-compose.yml | grep docker.sock || echo "docker.sock mount NOT found in docker-compose.yml"
    echo ""
    echo -e "${YELLOW}Manual fix required:${NC}"
    echo "1. Edit docker-compose.yml"
    echo "2. Under backend service volumes, add:"
    echo "   - /var/run/docker.sock:/var/run/docker.sock:ro"
    echo "3. Run: docker compose up -d backend"
    exit 1
fi

# 8. Test docker commands inside container
echo -e "\n${YELLOW}8. Testing docker commands inside container...${NC}"
if docker exec edgegate-backend docker ps >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend can execute docker commands${NC}"
else
    echo -e "${RED}✗ Backend CANNOT execute docker commands${NC}"
    echo "Checking permissions..."
    docker exec edgegate-backend ls -la /var/run/docker.sock
    exit 1
fi

# 9. Wait for backend to be healthy
echo -e "\n${YELLOW}9. Waiting for backend to be healthy...${NC}"
for i in {1..60}; do
    if docker inspect edgegate-backend 2>/dev/null | grep -q '"Status": "healthy"'; then
        echo -e "${GREEN}✓ Backend is healthy${NC}"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# 10. Test API
echo -e "\n${YELLOW}10. Testing backend API...${NC}"
sleep 2
if curl -f -s http://localhost/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend API is responding${NC}"
else
    echo -e "${YELLOW}⚠ API not responding yet, check logs${NC}"
    docker compose logs backend --tail 20
fi

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}  Docker socket fix completed!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "${GREEN}✓ You can now use Start/Stop/Restart buttons in the web interface${NC}"
echo ""
echo "Test commands:"
echo "  docker exec edgegate-backend docker ps"
echo "  docker exec edgegate-backend docker inspect edgegate-openvpn"
echo ""
echo "If issues persist, check logs:"
echo "  docker compose logs -f backend"
