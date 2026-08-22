#!/bin/bash
# Apply firewall rules dynamically
# Called by backend via docker exec

set -e

ACTION=${1:-reload}
NETWORK=${2:-}
FIREWALL_CONF="/etc/openvpn/firewall/allowed_networks.conf"
CLIENT_TO_CLIENT_FLAG="/etc/openvpn/firewall/client_to_client_enabled"
PUBLIC_INTERFACE=${PUBLIC_INTERFACE:-eth0}
OPENVPN_NETWORK=${OPENVPN_NETWORK:-10.8.0.0}

mkdir -p /etc/openvpn/firewall

case "$ACTION" in
    add)
        # Add network to allowed list
        if [ -z "$NETWORK" ]; then
            echo "ERROR: Network required for add action"
            exit 1
        fi
        # Check if already exists
        if grep -q "^${NETWORK}$" "$FIREWALL_CONF" 2>/dev/null; then
            echo "Network $NETWORK already in allowed list"
        else
            echo "$NETWORK" >> "$FIREWALL_CONF"
            echo "Added $NETWORK to allowed networks"
        fi
        # Reload rules
        $0 reload
        ;;

    remove)
        # Remove network from allowed list
        if [ -z "$NETWORK" ]; then
            echo "ERROR: Network required for remove action"
            exit 1
        fi
        if [ -f "$FIREWALL_CONF" ]; then
            grep -v "^${NETWORK}$" "$FIREWALL_CONF" > "${FIREWALL_CONF}.tmp" || true
            mv "${FIREWALL_CONF}.tmp" "$FIREWALL_CONF"
            echo "Removed $NETWORK from allowed networks"
        fi
        # Reload rules
        $0 reload
        ;;

    clear)
        # Clear all allowed networks
        > "$FIREWALL_CONF"
        echo "Cleared all allowed networks"
        # Reload rules
        $0 reload
        ;;

    client-to-client-enable)
        # Allow VPN clients to communicate with each other
        echo "Enabling client-to-client communication..."
        touch "$CLIENT_TO_CLIENT_FLAG"
        # Add tun0→tun0 rule in FORWARD chain (position 2, after ESTABLISHED,RELATED)
        # Remove first if exists to avoid duplicates
        iptables -D FORWARD -i tun0 -o tun0 -j ACCEPT 2>/dev/null || true
        iptables -I FORWARD 2 -i tun0 -o tun0 -j ACCEPT
        # Flush conntrack so existing sessions re-evaluate
        if command -v conntrack &>/dev/null; then
            conntrack -D -s ${OPENVPN_NETWORK}/24 2>/dev/null || true
        fi
        echo "Client-to-client communication ENABLED"
        ;;

    client-to-client-disable)
        # Block VPN clients from communicating with each other
        echo "Disabling client-to-client communication..."
        rm -f "$CLIENT_TO_CLIENT_FLAG"
        # Remove tun0→tun0 rule from FORWARD chain
        iptables -D FORWARD -i tun0 -o tun0 -j ACCEPT 2>/dev/null || true
        # Flush conntrack so active client-to-client sessions are dropped immediately
        if command -v conntrack &>/dev/null; then
            conntrack -D -s ${OPENVPN_NETWORK}/24 2>/dev/null || true
        fi
        echo "Client-to-client communication DISABLED (blocked by FORWARD DROP policy)"
        ;;

    list)
        # List allowed networks
        echo "=== Allowed Networks ==="
        if [ -f "$FIREWALL_CONF" ]; then
            cat "$FIREWALL_CONF"
        else
            echo "(none)"
        fi
        ;;

    reload)
        # Reload firewall rules
        echo "Reloading firewall rules..."

        # Flush VPN_FILTER chain
        iptables -F VPN_FILTER 2>/dev/null || iptables -N VPN_FILTER

        # ORDEM CORRETA DAS REGRAS:
        # 1. Primeiro: permitir redes internas configuradas (exceções ao bloqueio)
        if [ -f "$FIREWALL_CONF" ] && [ -s "$FIREWALL_CONF" ]; then
            while IFS= read -r network || [ -n "$network" ]; do
                [[ -z "$network" || "$network" =~ ^# ]] && continue
                echo "  Allowing internal network: $network"
                iptables -A VPN_FILTER -d "$network" -j ACCEPT
            done < "$FIREWALL_CONF"
        fi

        # 2. Bloquear todas as redes privadas (RFC1918)
        echo "  Blocking private networks..."
        iptables -A VPN_FILTER -d 10.0.0.0/8 -j DROP
        iptables -A VPN_FILTER -d 172.16.0.0/12 -j DROP
        iptables -A VPN_FILTER -d 192.168.0.0/16 -j DROP

        # 3. Permitir serviços para internet (destinos públicos)
        iptables -A VPN_FILTER -p icmp -j ACCEPT
        iptables -A VPN_FILTER -p udp --dport 53 -j ACCEPT
        iptables -A VPN_FILTER -p tcp --dport 80 -j ACCEPT
        iptables -A VPN_FILTER -p tcp --dport 443 -j ACCEPT

        # 4. Permitir todo o resto (internet)
        iptables -A VPN_FILTER -j ACCEPT

        # 5. Restore client-to-client rule if it was enabled
        # Remove any stale tun0→tun0 rule first
        iptables -D FORWARD -i tun0 -o tun0 -j ACCEPT 2>/dev/null || true
        if [ -f "$CLIENT_TO_CLIENT_FLAG" ]; then
            echo "  Restoring client-to-client ACCEPT rule..."
            iptables -I FORWARD 2 -i tun0 -o tun0 -j ACCEPT
        else
            echo "  Client-to-client blocked (default)"
        fi

        # 6. Flush conntrack entries for VPN clients
        # Without this, active connections continue passing through ESTABLISHED rule
        # even after removing the allow rule. Uses selective delete (-D -s) to only
        # clear sessions originated by VPN clients, preserving OpenVPN tunnel itself.
        if command -v conntrack &>/dev/null; then
            conntrack -D -s ${OPENVPN_NETWORK}/24 2>/dev/null && \
                echo "  Conntrack entries for VPN clients flushed" || \
                echo "  No conntrack entries to flush"
        fi

        echo "Firewall rules reloaded"
        ;;

    status)
        # Show current iptables rules
        echo "=== Client-to-Client ==="
        if [ -f "$CLIENT_TO_CLIENT_FLAG" ]; then
            echo "ENABLED (clients can communicate)"
        else
            echo "DISABLED (blocked by default)"
        fi
        echo ""
        echo "=== VPN_FILTER Chain ==="
        iptables -L VPN_FILTER -n -v --line-numbers 2>/dev/null || echo "Chain not found"
        echo ""
        echo "=== FORWARD Chain ==="
        iptables -L FORWARD -n -v --line-numbers
        echo ""
        echo "=== Allowed Networks Config ==="
        if [ -f "$FIREWALL_CONF" ]; then
            cat "$FIREWALL_CONF"
        else
            echo "(none)"
        fi
        ;;

    *)
        echo "Usage: $0 {add|remove|clear|list|reload|status|client-to-client-enable|client-to-client-disable} [network]"
        echo ""
        echo "Commands:"
        echo "  add <network>                Add network to allowed list (e.g., 10.0.2.0/24)"
        echo "  remove <network>             Remove network from allowed list"
        echo "  clear                        Remove all allowed networks"
        echo "  list                         List allowed networks"
        echo "  reload                       Reload firewall rules from config"
        echo "  status                       Show current firewall status"
        echo "  client-to-client-enable      Allow VPN clients to communicate"
        echo "  client-to-client-disable     Block VPN clients from communicating"
        exit 1
        ;;
esac
