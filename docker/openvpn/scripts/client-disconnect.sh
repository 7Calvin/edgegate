#!/bin/bash
#
# OpenVPN Client Disconnect Script
# Notifies backend when a client disconnects
#

BACKEND_URL="${BACKEND_URL:-http://backend:8000}"
LOG_FILE="/etc/openvpn/logs/connections.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] DISCONNECT: $1" >> "$LOG_FILE"
}

# Variables set by OpenVPN
USERNAME="$common_name"
VPN_IP="$ifconfig_pool_remote_ip"
BYTES_SENT="$bytes_sent"
BYTES_RECEIVED="$bytes_received"
DURATION="$time_duration"

log "$USERNAME disconnected ($VPN_IP) - sent: $BYTES_SENT, recv: $BYTES_RECEIVED, duration: ${DURATION}s"

# Notify backend
curl -s -X POST "${BACKEND_URL}/api/v1/vpn/connections/disconnect" \
    -H "Content-Type: application/json" \
    -H "X-OpenVPN-Secret: ${OPENVPN_SECRET:-}" \
    -d "{
        \"username\": \"$USERNAME\",
        \"vpn_ip\": \"$VPN_IP\",
        \"bytes_sent\": $BYTES_SENT,
        \"bytes_received\": $BYTES_RECEIVED,
        \"duration\": $DURATION
    }" \
    --connect-timeout 5 \
    --max-time 10 \
    > /dev/null 2>&1 || true

exit 0
