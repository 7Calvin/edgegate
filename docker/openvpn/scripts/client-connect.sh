#!/bin/bash
#
# OpenVPN Client Connect Script
# Notifies backend when a client connects
#

BACKEND_URL="${BACKEND_URL:-http://backend:8000}"
LOG_FILE="/etc/openvpn/logs/connections.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] CONNECT: $1" >> "$LOG_FILE"
}

# Variables set by OpenVPN
USERNAME="$common_name"
VPN_IP="$ifconfig_pool_remote_ip"
CLIENT_IP="$trusted_ip"
CLIENT_PORT="$trusted_port"

log "$USERNAME connected from $CLIENT_IP, assigned $VPN_IP"

# Notify backend
curl -s -X POST "${BACKEND_URL}/api/v1/vpn/connections/connect" \
    -H "Content-Type: application/json" \
    -H "X-OpenVPN-Secret: ${OPENVPN_SECRET:-}" \
    -d "{
        \"username\": \"$USERNAME\",
        \"vpn_ip\": \"$VPN_IP\",
        \"client_ip\": \"$CLIENT_IP\",
        \"client_port\": $CLIENT_PORT
    }" \
    --connect-timeout 5 \
    --max-time 10 \
    > /dev/null 2>&1 || true

exit 0
