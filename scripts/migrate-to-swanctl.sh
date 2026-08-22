#!/bin/bash
#
# migrate-to-swanctl.sh — one-shot migration of a legacy (stroke/ipsec.conf) box to
# swanctl/vici. Run ONCE per box, as root, in a maintenance window.
#
# Why a script and not a plain "click update": update.sh, the update-agent and the
# ipsec-agent run from ${INSTALL_DIR} (on the HOST, outside the docker-compose
# lifecycle) and are NOT refreshed by a normal update. So a legacy box updating to
# v1.5.0 would get the swanctl CODE running against the legacy DAEMON -> broken IPsec.
# This script bootstraps the migration-aware updater and runs the update, whose
# ensure_swanctl_mode switches the host IPsec daemon (strongswan-starter -> swanctl).
#
# IPsec connections are PRESERVED (the backend regenerates the swanctl config from the
# DB — you do NOT need to recreate them). The tunnel drops briefly during the switch.
#
set -uo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/edgegate}"
REPO_DIR="${REPO_DIR:-${INSTALL_DIR}/repo}"
GIT_REMOTE="${GIT_REMOTE:-https://github.com/7Calvin/edgegate.git}"
REPO_SUBDIR=""
TARGET="${TARGET:-v1.5.2}"

log() { echo "[migrate-to-swanctl] $*"; }

[ "$(id -u)" = "0" ] || { echo "Please run as root (sudo)."; exit 1; }

log "Target version: ${TARGET}"

# 1. Ensure the source repo exists with the target checked out (to copy the new
#    update.sh from). update.sh will re-checkout on its own; this only fetches the file.
if [ ! -d "${REPO_DIR}/.git" ]; then
    log "Cloning source repo -> ${REPO_DIR}"
    git clone "${GIT_REMOTE}" "${REPO_DIR}"
fi
git -C "${REPO_DIR}" fetch --tags --prune origin
git -C "${REPO_DIR}" checkout -f "${TARGET}"
if [ -n "$REPO_SUBDIR" ]; then SRC="${REPO_DIR}/${REPO_SUBDIR}"; else SRC="${REPO_DIR}"; fi
[ -d "$SRC" ] || { echo "source subdir not found: $SRC"; exit 1; }

# 2. Bootstrap the migration-aware update.sh into the update-agent run-dir so IT is the
#    one that executes the update (the box's own update.sh is too old to auto-migrate).
UPD="${SRC}/docker/update-agent/update.sh"
if [ -d "${INSTALL_DIR}/update-agent" ]; then
    cp -f "${UPD}" "${INSTALL_DIR}/update-agent/update.sh"
    chmod +x "${INSTALL_DIR}/update-agent/update.sh"
    UPD="${INSTALL_DIR}/update-agent/update.sh"
    log "Bootstrapped migration-aware update.sh into ${INSTALL_DIR}/update-agent"
fi

# 3. Run the update to the target. Its ensure_swanctl_mode installs swanctl, switches
#    the host daemon (strongswan-starter -> strongswan/vici), masks the starter and
#    refreshes the ipsec-agent; the rebuilt backend then regenerates the swanctl config
#    from the DB and the tunnels come back up in swanctl.
log "Running the migration update to ${TARGET} — the IPsec tunnel will drop briefly..."
UPDATE_REF="${TARGET}" bash "${UPD}"
rc=$?

echo
if [ "$rc" = "0" ]; then
    log "Migration finished. Verify with:"
    log "  systemctl is-active strongswan   (expect: active)"
    log "  swanctl --list-sas               (expect your tunnels ESTABLISHED)"
else
    log "Update returned ${rc} — check ${INSTALL_DIR}/../var/lib/edgegate-update/update.log (or /var/lib/edgegate-update/update.log)"
fi
exit "$rc"
