#!/bin/bash
#
# OpenVPN Authentication Script
# Validates credentials against the backend API
#

BACKEND_URL="${BACKEND_URL:-http://edgegate-backend:8000}"
LOG_FILE="/etc/openvpn/logs/auth.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Get credentials from environment (set by OpenVPN)
USERNAME="$username"
PASSWORD="$password"
CLIENT_IP="$untrusted_ip"

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    log "AUTH FAILED: Empty credentials from $CLIENT_IP"
    exit 1
fi

log "AUTH ATTEMPT: $USERNAME from $CLIENT_IP"

# Call backend API
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "${BACKEND_URL}/api/v1/vpn/auth" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$USERNAME\", \"password\": \"$PASSWORD\", \"client_ip\": \"$CLIENT_IP\"}" \
    --connect-timeout 5 \
    --max-time 10)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    log "AUTH SUCCESS: $USERNAME from $CLIENT_IP"
    exit 0
else
    log "AUTH FAILED: $USERNAME from $CLIENT_IP - HTTP $HTTP_CODE"
    exit 1
fi
