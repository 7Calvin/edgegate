#!/bin/sh
# edgegate-xfrm.sh - recreate route-based XFRM interfaces BEFORE strongSwan loads conns.
#
# Fixes the boot race (v2.2.0 route-based IPsec): on boot the peer brings the tunnel up
# (strongswan ExecStartPost `swanctl --load-all` + start_action=start, and the FortiGate
# also initiates) BEFORE the ipsec-agent creates the eg-* XFRM interfaces. The CHILD_SA
# updown then fails with `Cannot find device "eg-NNNN"`, the route never installs, and
# traffic blackholes ("established/online" but dead) until a manual tunnel restart.
#
# Creating the interfaces up-front, ordered Before=strongswan.service, lets the very first
# CHILD_SA install its route via updown. Idempotent; reads the same conf.d charon loads,
# so it stays in sync automatically (no separate spec file to maintain).
CONF_DIR=/etc/swanctl/conf.d
MTU="${RB_XFRM_MTU:-1400}"

log() { logger -t edgegate-xfrm "$*" 2>/dev/null || true; echo "edgegate-xfrm: $*"; }

PHYS="$(ip -o -4 route show default 2>/dev/null | awk '{print $5; exit}')"
[ -n "$PHYS" ] || PHYS=ens5

# Distinct if_id values from the route-based connections (eg-<if_id> = XFRM ifname).
IFIDS="$(grep -rhoE 'if_id_(in|out) = [0-9]+' "$CONF_DIR" 2>/dev/null | grep -oE '[0-9]+' | sort -un)"
if [ -z "$IFIDS" ]; then
    log "no route-based if_id in $CONF_DIR - nothing to do"
    exit 0
fi

for IFID in $IFIDS; do
    NAME="eg-$IFID"
    if ip link show "$NAME" >/dev/null 2>&1; then
        log "$NAME already present"
    elif ip link add "$NAME" type xfrm if_id "$IFID" dev "$PHYS" 2>/dev/null; then
        log "created $NAME (if_id=$IFID dev=$PHYS)"
    else
        log "FAILED to create $NAME (if_id=$IFID dev=$PHYS)"
        continue
    fi
    ip link set "$NAME" up 2>/dev/null || true
    ip link set "$NAME" mtu "$MTU" 2>/dev/null || true
done
log "done (phys=$PHYS mtu=$MTU)"
exit 0
