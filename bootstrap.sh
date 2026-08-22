#!/usr/bin/env bash
#
# EdgeGate - one-line installer / bootstrapper
#
# Usage (fresh Ubuntu 24.04):
#
#   # Guided (interactive) install — download then run so stdin stays a real TTY:
#   curl -fsSL <url>/bootstrap.sh -o vpn-install.sh && sudo bash vpn-install.sh
#
#   # Unattended one-liner (no prompts) — sensible defaults, just give the domain:
#   curl -fsSL <url>/bootstrap.sh | sudo NONINTERACTIVE=1 DOMAIN=vpn.example.com bash
#
#   # Pin a specific release:
#   curl -fsSL <url>/bootstrap.sh | sudo VPN_REPO_REF=v1.1.3 NONINTERACTIVE=1 DOMAIN=... bash
#
# What it does:
#   1. installs the minimal tools needed to fetch the source (git, curl)
#   2. clones (or updates) the repository into /opt/edgegate-src
#   3. runs install.sh (reconnected to /dev/tty when a terminal is available, so
#      the guided installer works; falls back to non-interactive otherwise)
#
set -euo pipefail

REPO_URL="${VPN_REPO_URL:-https://github.com/7Calvin/edgegate.git}"
REPO_REF="${VPN_REPO_REF:-main}"          # branch or tag
SUBDIR="${VPN_REPO_SUBDIR:-}"          # empty = app at repo root
SRC_DIR="${VPN_SRC_DIR:-/opt/edgegate-src}"

# --- Colors (only when attached to a terminal) ---
if [ -t 1 ]; then
    BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
else
    BLUE=''; GREEN=''; RED=''; NC=''
fi
say()  { echo -e "${BLUE}==>${NC} $*"; }
ok()   { echo -e "${GREEN}==>${NC} $*"; }
die()  { echo -e "${RED}error:${NC} $*" >&2; exit 1; }

# --- Must be root ---
if [ "$(id -u)" -ne 0 ]; then
    die "run as root, e.g.:  curl -fsSL <url>/bootstrap.sh | sudo bash"
fi

# --- Minimal prerequisites to clone the repo ---
say "Installing prerequisites (git, curl)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates >/dev/null

# --- Clone or update the source ---
if [ -d "$SRC_DIR/.git" ]; then
    say "Updating existing source in $SRC_DIR ..."
    git -C "$SRC_DIR" fetch --tags --prune --depth 1 origin "$REPO_REF"
    git -C "$SRC_DIR" checkout -f "$REPO_REF"
    git -C "$SRC_DIR" reset --hard "origin/$REPO_REF" 2>/dev/null || true
else
    say "Cloning $REPO_URL ($REPO_REF) into $SRC_DIR ..."
    rm -rf "$SRC_DIR"
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$SRC_DIR" 2>/dev/null \
        || git clone "$REPO_URL" "$SRC_DIR"   # fallback if REF is a specific commit
fi

APP_DIR="$SRC_DIR${SUBDIR:+/$SUBDIR}"
[ -f "$APP_DIR/install.sh" ] || die "install.sh not found under $APP_DIR"
chmod +x "$APP_DIR/install.sh"

ok "Source ready. Launching installer..."
cd "$APP_DIR"

# Run the installer. If a terminal is available and the caller didn't force
# NONINTERACTIVE, reconnect stdin to /dev/tty so the guided whiptail installer
# runs (a curl | bash pipe otherwise leaves stdin non-interactive).
# NOTE: we no longer `exec` — we run it and keep control so we can tidy up the
# temporary source clone afterwards.
run_installer() {
    if [ -z "${NONINTERACTIVE:-}" ] && [ -e /dev/tty ]; then
        ./install.sh < /dev/tty
    else
        ./install.sh
    fi
}

rc=0
run_installer || rc=$?

# On success, remove the bootstrap source clone. The application was copied into
# /opt/edgegate by the installer, and the update-agent keeps its OWN clone
# (lazily created under /opt/edgegate/repo on the first update check), so
# this temporary checkout is not needed at runtime. Set KEEP_SRC=1 to keep it for
# debugging.
if [ "$rc" -eq 0 ] && [ -z "${KEEP_SRC:-}" ] && [ -n "$SRC_DIR" ] && [ "$SRC_DIR" != "/" ]; then
    cd /
    rm -rf "$SRC_DIR"
    ok "Cleaned up temporary source at $SRC_DIR"
fi

exit "$rc"
