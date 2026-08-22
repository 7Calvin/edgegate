#!/bin/bash
#
# EdgeGate - Installation Script
# Compatible with Ubuntu 24.04 LTS
#
# Usage: sudo ./install.sh
#
# Non-interactive mode (skip TUI prompts):
#   NONINTERACTIVE=1 DOMAIN=vpn.example.com DB_TYPE=local ./install.sh
#

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Application version (source of truth: the VERSION file next to this script)
APP_VERSION="$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]')"
APP_VERSION="${APP_VERSION:-1.0.0}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Defaults
DEFAULT_VPN_NETWORK="10.8.0.0"
DEFAULT_VPN_NETMASK="255.255.255.0"
DEFAULT_VPN_PORT="1194"
# Public uplink interface (auto-detected from the default route, fallback eth0)
DEFAULT_PUBLIC_INTERFACE="$(ip route show default 2>/dev/null | awk '/default/{print $5; exit}')"
DEFAULT_PUBLIC_INTERFACE="${DEFAULT_PUBLIC_INTERFACE:-eth0}"
# Private subnet that uses this host as a NAT gateway (optional; empty = disabled)
DEFAULT_NAT_GATEWAY_NETWORK=""
DEFAULT_WEB_PORT="443"
DEFAULT_DB_PORT="5432"
INSTALL_DIR="/opt/edgegate"

# ==================== Interactive Mode Detection ====================

INTERACTIVE=true
if [ -n "$NONINTERACTIVE" ] || [ ! -t 0 ]; then
    INTERACTIVE=false
fi

# Ensure whiptail is available for interactive mode
if $INTERACTIVE; then
    if ! command -v whiptail &>/dev/null; then
        echo "Installing whiptail..."
        apt-get update -qq && apt-get install -y -qq whiptail || {
            echo "Failed to install whiptail. Install it manually or use NONINTERACTIVE=1"
            exit 1
        }
    fi
fi

# Terminal dimensions for whiptail
calc_wh_size() {
    WT_HEIGHT=20
    WT_WIDTH=70
    WT_MENU_HEIGHT=$((WT_HEIGHT - 8))
}
calc_wh_size

# ==================== TUI Wrapper Functions ====================

# Handle cancel/ESC from whiptail dialogs
wt_cancel() {
    if $INTERACTIVE; then
        if whiptail --title "Cancel" --yesno "Are you sure you want to cancel the installation?" 8 $WT_WIDTH; then
            echo "Installation cancelled by user."
            exit 1
        fi
        return 1  # User chose not to cancel, caller should retry
    else
        echo "Installation cancelled."
        exit 1
    fi
}

# Display informational message box
wt_msgbox() {
    local title=$1 msg=$2
    if $INTERACTIVE; then
        whiptail --title "$title" --msgbox "$msg" $WT_HEIGHT $WT_WIDTH
    fi
    # Non-interactive: stay quiet — the banner and the final summary already
    # cover this, and echoing raw messages (with literal \n) just adds noise.
}

# Yes/No question. Returns 0 for yes, 1 for no.
# Usage: wt_yesno "Title" "Question?" [default_yes|default_no]
wt_yesno() {
    local title=$1 msg=$2 default=${3:-default_yes}
    local env_var=$4  # optional env var name to check

    # Check env var first
    if [ -n "$env_var" ]; then
        local val="${!env_var}"
        if [ -n "$val" ]; then
            [[ "$val" =~ ^(true|yes|y|1)$ ]] && return 0 || return 1
        fi
    fi

    if $INTERACTIVE; then
        local default_flag=""
        [ "$default" = "default_no" ] && default_flag="--defaultno"
        while true; do
            local exit_code=0
            whiptail --title "$title" --yesno $default_flag "$msg" $WT_HEIGHT $WT_WIDTH || exit_code=$?
            if [ $exit_code -eq 0 ]; then
                return 0
            elif [ $exit_code -eq 255 ]; then
                # ESC pressed
                wt_cancel || continue
            else
                return 1
            fi
        done
    else
        # Non-interactive: use default
        [ "$default" = "default_yes" ] && return 0 || return 1
    fi
}

# Input box with validation support
# Usage: wt_input VAR_NAME "Title" "Prompt text" [default] [optional]
# Pass "optional" as the 5th arg for fields where an empty value is valid
# (e.g. features that are simply disabled when left blank). Without it, a field
# with no default is treated as required and aborts in non-interactive mode.
wt_input() {
    local var_name=$1 title=$2 prompt_text=$3 default=$4 optional=${5:-}

    # Check if env var already set
    local current_val="${!var_name}"
    if [ -n "$current_val" ]; then
        eval "$var_name=\$current_val"
        return 0
    fi

    if $INTERACTIVE; then
        local result
        while true; do
            result=$(whiptail --title "$title" --inputbox "$prompt_text" $WT_HEIGHT $WT_WIDTH "$default" 3>&1 1>&2 2>&3)
            local exit_code=$?
            if [ $exit_code -eq 0 ]; then
                eval "$var_name=\$result"
                return 0
            else
                wt_cancel || continue
            fi
        done
    else
        # Non-interactive: use default, accept empty if optional, else fail
        if [ -n "$default" ] || [ "$optional" = "optional" ]; then
            eval "$var_name=\$default"
            return 0
        else
            log_error "Required value for $var_name not provided (non-interactive mode)"
            exit 1
        fi
    fi
}

# Password input box (hidden text)
# Usage: wt_password VAR_NAME "Title" "Prompt text"
wt_password() {
    local var_name=$1 title=$2 prompt_text=$3

    # Check if env var already set
    local current_val="${!var_name}"
    if [ -n "$current_val" ]; then
        eval "$var_name=\$current_val"
        return 0
    fi

    if $INTERACTIVE; then
        local result
        while true; do
            result=$(whiptail --title "$title" --passwordbox "$prompt_text" $WT_HEIGHT $WT_WIDTH 3>&1 1>&2 2>&3)
            local exit_code=$?
            if [ $exit_code -eq 0 ]; then
                eval "$var_name=\$result"
                return 0
            else
                wt_cancel || continue
            fi
        done
    else
        log_error "Required password for $var_name not provided (non-interactive mode)"
        exit 1
    fi
}

# Menu selection (radio-style)
# Usage: wt_menu VAR_NAME "Title" "Prompt" "tag1" "description1" "tag2" "description2" ...
wt_menu() {
    local var_name=$1 title=$2 prompt_text=$3
    shift 3

    # Check if env var already set
    local current_val="${!var_name}"
    if [ -n "$current_val" ]; then
        eval "$var_name=\$current_val"
        return 0
    fi

    if $INTERACTIVE; then
        local result
        while true; do
            result=$(whiptail --title "$title" --menu "$prompt_text" $WT_HEIGHT $WT_WIDTH $WT_MENU_HEIGHT "$@" 3>&1 1>&2 2>&3)
            local exit_code=$?
            if [ $exit_code -eq 0 ]; then
                eval "$var_name=\$result"
                return 0
            else
                wt_cancel || continue
            fi
        done
    else
        # Non-interactive: use first option as default
        eval "$var_name=\$1"
        return 0
    fi
}

# Progress gauge
# Usage: command_producing_progress | wt_gauge "Title" "Initial message"
wt_gauge() {
    local title=$1 msg=$2
    if $INTERACTIVE; then
        whiptail --title "$title" --gauge "$msg" 8 $WT_WIDTH 0
    else
        # Non-interactive: just consume stdin and show log messages
        while IFS= read -r line; do
            # Parse gauge format: number or "XXX\nmessage\nXXX"
            if [[ "$line" =~ ^[0-9]+$ ]]; then
                true  # skip percentage lines
            elif [ "$line" != "XXX" ]; then
                echo "  $line"
            fi
        done
    fi
}

# ==================== Helper Functions ====================

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║                                                           ║"
    echo "║           EdgeGate Installer                 ║"
    printf "║%*sv%s%*s║\n" $(( (59 - ${#APP_VERSION} - 1) / 2 )) "" "$APP_VERSION" $(( 59 - ${#APP_VERSION} - 1 - (59 - ${#APP_VERSION} - 1) / 2 )) ""
    echo "║                                                           ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

generate_password() {
    openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 24
}

generate_secret() {
    openssl rand -hex 32
}

validate_domain() {
    local domain=$1
    if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$ ]]; then
        return 1
    fi
    return 0
}

validate_ip() {
    local ip=$1
    if [[ ! "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        return 1
    fi
    return 0
}

validate_email() {
    local email=$1
    if [[ ! "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        return 1
    fi
    return 0
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root"
        echo "Please run: sudo $0"
        exit 1
    fi
}

check_ubuntu() {
    if [ ! -f /etc/os-release ]; then
        log_error "Cannot detect OS"
        exit 1
    fi

    source /etc/os-release

    if [ "$ID" != "ubuntu" ]; then
        log_warn "This script is designed for Ubuntu. Detected: $ID"
        if ! wt_yesno "OS Warning" \
            "This script is designed for Ubuntu.\n\nDetected: $ID\n\nContinue anyway?" \
            "default_no"; then
            exit 1
        fi
    fi

    log_success "Detected: $PRETTY_NAME"
}

# ==================== Installation Functions ====================

install_dependencies() {
    log_info "Installing system dependencies..."

    apt-get update -qq
    apt-get install -y -qq \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        openssl \
        ufw \
        jq \
        git \
        python3 \
        python3-pip \
        python3-venv \
        rsync

    log_success "System dependencies installed"
}

install_strongswan() {
    log_info "Installing StrongSwan (IPsec)..."

    # The stack runs strongSwan in **swanctl/vici** mode (not legacy stroke/ipsec.conf),
    # so we install swanctl + charon-systemd. strongswan-pki/extra-plugins for ciphers.
    apt-get install -y -qq strongswan-swanctl charon-systemd strongswan-pki libcharon-extra-plugins || \
        apt-get install -y -qq strongswan strongswan-swanctl strongswan-pki libcharon-extra-plugins || \
        log_warn "Could not install swanctl packages (IPsec features may be unavailable)"

    # Tighten IKE retransmit timing so a dead peer is detected in ~30s (for IPsec
    # HA/failover) instead of the stock ~2min. Paired with per-connection dpd_delay=10s
    # in the generated swanctl config. Idempotent; the restart below picks it up.
    if [ -f /etc/strongswan.conf ] && ! grep -q "retransmit_tries" /etc/strongswan.conf; then
        python3 - <<'PYEOF' 2>/dev/null || true
p = "/etc/strongswan.conf"
s = open(p).read()
if "charon {" in s and "retransmit_tries" not in s:
    s = s.replace("charon {\n",
                  "charon {\n\tretransmit_timeout = 2.0\n\tretransmit_base = 1.6\n\tretransmit_tries = 4\n", 1)
    open(p, "w").write(s)
PYEOF
    fi

    # Use the swanctl daemon (strongswan.service) and MASK the legacy starter so it can
    # never auto-start (the `ipsec` CLI would otherwise revive it and it fights swanctl
    # for the vici socket). Kill any orphan legacy charon holding UDP 500/4500 first.
    systemctl stop strongswan-starter 2>/dev/null || true
    systemctl mask strongswan-starter 2>/dev/null || true
    pkill -9 -f '/usr/lib/ipsec/' 2>/dev/null || true
    if systemctl list-unit-files 2>/dev/null | grep -q "^strongswan\.service"; then
        systemctl enable strongswan 2>/dev/null || true
        systemctl restart strongswan 2>/dev/null || true
        sleep 2
        if [ -S /var/run/charon.vici ] && swanctl --stats >/dev/null 2>&1; then
            log_success "StrongSwan running in swanctl/vici mode"
        else
            log_warn "strongswan.service started but vici not confirmed (IPsec optional)"
        fi
    else
        log_warn "No strongswan.service unit found; skipping (IPsec optional)"
    fi

    # Create MSS clamping + UFW route leftupdown script
    # This script is called by StrongSwan when tunnels go up/down
    # It handles: MSS clamping (prevents TCP fragmentation in ESP tunnel)
    #             UFW route rules (allows forwarding between VPN subnets)
    mkdir -p /etc/ipsec.d
    cat > /etc/ipsec.d/mss-clamp.sh << 'MSSEOF'
#!/bin/bash
# =============================================================
# StrongSwan leftupdown script - MSS Clamping + Firewall Rules
# Called automatically when IPsec tunnels go up/down
#
# Solves: TCP packets > ~1422 bytes being dropped in ESP tunnel
#         (e.g. RDP/NLA/CredSSP authentication failures)
#
# StrongSwan provides these environment variables:
#   PLUTO_VERB:        up-client, down-client, etc.
#   PLUTO_PEER_CLIENT: remote subnet (e.g., 192.168.0.0/24)
#   PLUTO_MY_CLIENT:   local subnet (e.g., 10.110.0.0/16)
# =============================================================

# MSS value: 1360 allows for ESP overhead on interfaces with
# MTU 9001 (AWS jumbo) or standard 1500 MTU
MSS_VALUE=1360

case "$PLUTO_VERB" in
    up-client)
        # --- MSS Clamping: FORWARD chain (routed traffic through tunnel) ---
        # Uses IPsec policy match - only affects packets in active SAs
        # Check before adding to avoid duplicates from multiple tunnels
        if ! iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN \
            -m policy --pol ipsec --dir in -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null; then
            iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
                -m policy --pol ipsec --dir in -j TCPMSS --set-mss $MSS_VALUE
        fi
        if ! iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN \
            -m policy --pol ipsec --dir out -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null; then
            iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
                -m policy --pol ipsec --dir out -j TCPMSS --set-mss $MSS_VALUE
        fi

        # --- MSS Clamping: OUTPUT chain (traffic from this host to remote) ---
        if ! iptables -t mangle -C OUTPUT -p tcp --tcp-flags SYN,RST SYN \
            -d "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null; then
            iptables -t mangle -A OUTPUT -p tcp --tcp-flags SYN,RST SYN \
                -d "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE
        fi

        # --- MSS Clamping: INPUT chain (traffic from remote to this host) ---
        if ! iptables -t mangle -C INPUT -p tcp --tcp-flags SYN,RST SYN \
            -s "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null; then
            iptables -t mangle -A INPUT -p tcp --tcp-flags SYN,RST SYN \
                -s "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE
        fi

        # --- UFW route rules (allow forwarding between VPN subnets) ---
        if command -v ufw >/dev/null 2>&1; then
            ufw route allow from "$PLUTO_MY_CLIENT" to "$PLUTO_PEER_CLIENT" 2>/dev/null || true
            ufw route allow from "$PLUTO_PEER_CLIENT" to "$PLUTO_MY_CLIENT" 2>/dev/null || true
        fi
        ;;

    down-client)
        # Remove subnet-specific MSS rules (OUTPUT/INPUT)
        iptables -t mangle -D OUTPUT -p tcp --tcp-flags SYN,RST SYN \
            -d "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null || true
        iptables -t mangle -D INPUT -p tcp --tcp-flags SYN,RST SYN \
            -s "$PLUTO_PEER_CLIENT" -j TCPMSS --set-mss $MSS_VALUE 2>/dev/null || true
        # Note: FORWARD rules with policy match are kept (safe for other tunnels,
        # harmless when no tunnels active since -m policy only matches IPsec SAs)
        # Note: UFW route rules are kept (persistent, needed if tunnel reconnects)
        ;;
esac
MSSEOF
    chmod +x /etc/ipsec.d/mss-clamp.sh

    log_success "StrongSwan configured"
    log_success "MSS clamping script created at /etc/ipsec.d/mss-clamp.sh"
}

install_ipsec_agent() {
    log_info "Installing IPsec Agent..."

    IPSEC_AGENT_DIR="/opt/edgegate/ipsec-agent"
    mkdir -p "$IPSEC_AGENT_DIR"

    # Copy agent files
    cp "${SCRIPT_DIR}/docker/ipsec-agent/app.py" "$IPSEC_AGENT_DIR/"
    cp "${SCRIPT_DIR}/docker/ipsec-agent/requirements.txt" "$IPSEC_AGENT_DIR/"

    # Create virtual environment
    log_info "  Creating Python virtual environment..."
    python3 -m venv "$IPSEC_AGENT_DIR/venv"
    source "$IPSEC_AGENT_DIR/venv/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$IPSEC_AGENT_DIR/requirements.txt" -q
    deactivate

    # Save token
    echo "$IPSEC_AGENT_TOKEN" > /opt/edgegate/ipsec-agent.token
    chmod 600 /opt/edgegate/ipsec-agent.token

    # Create systemd service
    cat > /etc/systemd/system/ipsec-agent.service << EOF
[Unit]
Description=IPsec Agent for EdgeGate
After=network.target strongswan.service
Wants=strongswan.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$IPSEC_AGENT_DIR
Environment="IPSEC_AGENT_TOKEN=$IPSEC_AGENT_TOKEN"
Environment="IPSEC_AGENT_PORT=8101"
ExecStart=$IPSEC_AGENT_DIR/venv/bin/gunicorn -w 2 -b 0.0.0.0:8101 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Start service (optional component — never abort the install if it fails)
    systemctl daemon-reload || true
    systemctl enable ipsec-agent 2>/dev/null || true
    systemctl restart ipsec-agent 2>/dev/null || log_warn "IPsec Agent did not start (IPsec optional)"

    log_success "IPsec Agent installed"
}

install_update_agent() {
    log_info "Installing Update Agent..."

    UPDATE_AGENT_DIR="/opt/edgegate/update-agent"
    UPDATE_GIT_REMOTE="${UPDATE_GIT_REMOTE:-https://github.com/7Calvin/edgegate.git}"
    UPDATE_GIT_BRANCH="${UPDATE_GIT_BRANCH:-main}"
    UPDATE_AGENT_TOKEN="${UPDATE_AGENT_TOKEN:-$(generate_secret)}"
    mkdir -p "$UPDATE_AGENT_DIR" /var/lib/edgegate-update

    # Copy agent files (app + orchestrator script)
    cp "${SCRIPT_DIR}/docker/update-agent/app.py" "$UPDATE_AGENT_DIR/"
    cp "${SCRIPT_DIR}/docker/update-agent/requirements.txt" "$UPDATE_AGENT_DIR/"
    cp "${SCRIPT_DIR}/docker/update-agent/update.sh" "$UPDATE_AGENT_DIR/"
    chmod +x "$UPDATE_AGENT_DIR/update.sh"

    # Python virtual environment
    log_info "  Creating Python virtual environment..."
    python3 -m venv "$UPDATE_AGENT_DIR/venv"
    source "$UPDATE_AGENT_DIR/venv/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$UPDATE_AGENT_DIR/requirements.txt" -q
    deactivate

    # Save token
    echo "$UPDATE_AGENT_TOKEN" > /opt/edgegate/update-agent.token
    chmod 600 /opt/edgegate/update-agent.token

    # systemd service
    cat > /etc/systemd/system/update-agent.service << EOF
[Unit]
Description=Update Agent for EdgeGate
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$UPDATE_AGENT_DIR
Environment="UPDATE_AGENT_TOKEN=$UPDATE_AGENT_TOKEN"
Environment="UPDATE_AGENT_PORT=8102"
Environment="INSTALL_DIR=/opt/edgegate"
Environment="REPO_DIR=/opt/edgegate/repo"
Environment="STATE_DIR=/var/lib/edgegate-update"
Environment="UPDATE_SCRIPT=$UPDATE_AGENT_DIR/update.sh"
Environment="GIT_REMOTE=$UPDATE_GIT_REMOTE"
Environment="GIT_BRANCH=$UPDATE_GIT_BRANCH"
Environment="ENV_FILE=/opt/edgegate/config/.env"
Environment="COMPOSE_FILE=/opt/edgegate/docker-compose.yml"
# Self-heal: on every start, adopt the agent code of the currently-deployed version.
# update.sh syncs it into /opt/edgegate/docker/update-agent on EVERY update
# (forward OR rollback), so this keeps the running agent in lock-step with the system
# version without any logic inside update.sh — a rollback through an older version and
# back never strands the agent (and its /tags endpoint) on stale code.
ExecStartPre=/bin/sh -c 'for f in app.py update.sh; do s=/opt/edgegate/docker/update-agent/\$f; [ -f "\$s" ] && cp -f "\$s" $UPDATE_AGENT_DIR/\$f; done; chmod +x $UPDATE_AGENT_DIR/update.sh 2>/dev/null; exit 0'
ExecStart=$UPDATE_AGENT_DIR/venv/bin/gunicorn -w 2 -t 300 -b 0.0.0.0:8102 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Refresh guard: restart the agent to adopt freshly-synced code, but only AFTER any
    # in-flight update has finished — so it can never kill a running updater (which may
    # share the agent's systemd cgroup on older versions).
    cat > "$UPDATE_AGENT_DIR/refresh-guard.sh" << 'EOF'
#!/bin/sh
STATUS=/var/lib/edgegate-update/status.json
# Wait out an in-progress update (up to ~30 min) before restarting the agent.
i=0
while [ "$i" -lt 180 ]; do
    grep -q '"state": "running"' "$STATUS" 2>/dev/null || break
    sleep 10
    i=$((i + 1))
done
exec systemctl restart update-agent
EOF
    chmod +x "$UPDATE_AGENT_DIR/refresh-guard.sh"

    # Watcher: when update.sh syncs new agent code into docker/update-agent (every
    # update), restart the agent (via the guard) so its ExecStartPre re-adopts it. The
    # trigger is the file change, not update.sh logic, so it works for ANY updater
    # version — this is what makes rollbacks through old versions self-heal.
    cat > /etc/systemd/system/update-agent-refresh.service << EOF
[Unit]
Description=Refresh update-agent to the deployed version

[Service]
Type=oneshot
ExecStart=$UPDATE_AGENT_DIR/refresh-guard.sh
EOF

    cat > /etc/systemd/system/update-agent-refresh.path << EOF
[Unit]
Description=Watch for refreshed update-agent code and reload it

[Path]
PathChanged=/opt/edgegate/docker/update-agent/app.py
PathChanged=/opt/edgegate/docker/update-agent/update.sh
Unit=update-agent-refresh.service

[Install]
WantedBy=multi-user.target
EOF

    # Start service (optional component — never abort the install if it fails)
    systemctl daemon-reload || true
    systemctl enable update-agent 2>/dev/null || true
    systemctl enable update-agent-refresh.path 2>/dev/null || true
    systemctl start update-agent-refresh.path 2>/dev/null || true
    systemctl restart update-agent 2>/dev/null || log_warn "Update Agent did not start"

    log_success "Update Agent installed"
}

install_docker() {
    if command -v docker &> /dev/null; then
        log_success "Docker already installed: $(docker --version)"
        return
    fi

    log_info "Installing Docker..."

    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    # Add repository
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Enable and start Docker
    systemctl enable docker
    systemctl start docker

    log_success "Docker installed: $(docker --version)"
}

configure_ipsec_sysctl() {
    # Ensure sysctl settings for IPsec are in place (idempotent)
    # Can be called from both fresh install and upgrade paths
    cat > /etc/sysctl.d/99-vpn-ipsec.conf << 'SYSEOF'
# EdgeGate - IP forwarding and IPsec tweaks
net.ipv4.ip_forward=1

# Disable reverse path filtering for IPsec
# Required: packets arriving from IPsec tunnel have source IPs
# from remote subnets, which would fail rp_filter strict mode
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0

# Accept redirects (needed for some IPsec routing scenarios)
net.ipv4.conf.all.accept_redirects=1
net.ipv4.conf.all.send_redirects=1
SYSEOF
    # Best-effort tweak to the legacy monolithic sysctl file. Newer Ubuntu
    # (25.10+/26.04) ships no /etc/sysctl.conf — it uses /etc/sysctl.d drop-ins,
    # which we already wrote above. Guard so `set -e` doesn't abort the install.
    if [ -f /etc/sysctl.conf ]; then
        sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf || true
    fi
    sysctl --system > /dev/null 2>&1 || true

    # Allow ESP protocol through UFW
    if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
        ufw allow proto esp from any to any comment 'IPsec ESP' 2>/dev/null || true
    fi

    log_success "IPsec sysctl settings applied (ip_forward=1, rp_filter=0)"
}

configure_firewall() {
    log_info "Configuring firewall..."

    # Enable UFW
    ufw --force enable

    # Allow SSH
    ufw allow ssh

    # Allow HTTP/HTTPS
    ufw allow 80/tcp
    ufw allow 443/tcp

    # Allow OpenVPN
    ufw allow ${VPN_PORT}/udp

    # Allow IPsec (StrongSwan)
    ufw allow 500/udp comment 'IPsec IKE'
    ufw allow 4500/udp comment 'IPsec NAT-T'

    # Allow NAT agent and IPsec agent from Docker networks
    ufw allow from 172.17.0.0/16 to any port 8100 comment 'NAT Agent'
    ufw allow from 172.20.0.0/16 to any port 8100 comment 'NAT Agent VPN Network'
    ufw allow from 172.17.0.0/16 to any port 8101 comment 'IPsec Agent'
    ufw allow from 172.20.0.0/16 to any port 8101 comment 'IPsec Agent VPN Network'
    ufw allow from 172.17.0.0/16 to any port 8102 comment 'Update Agent'
    ufw allow from 172.20.0.0/16 to any port 8102 comment 'Update Agent VPN Network'

    # Enable IP forwarding + IPsec sysctl tweaks + ESP protocol
    configure_ipsec_sysctl

    log_success "Firewall configured"
}

create_directory_structure() {
    log_info "Creating directory structure..."

    mkdir -p ${INSTALL_DIR}/{config,data,logs,certs,backups}
    mkdir -p ${INSTALL_DIR}/data/{postgres,redis,openvpn,backend}
    mkdir -p ${INSTALL_DIR}/config/openvpn

    # Seed the VPN client allow-list with the configured NAT gateway network so
    # internal-network access works out of the box. Without this, VPN_FILTER drops
    # traffic to the internal net (it falls under the 10.0.0.0/8 DROP) and clients
    # can't reach it until an admin adds it manually. start.sh reads this file on
    # boot; we only seed (append-if-absent) so an existing list is never clobbered.
    if [ -n "${NAT_GATEWAY_NETWORK}" ]; then
        mkdir -p ${INSTALL_DIR}/data/openvpn/firewall
        local allow_file="${INSTALL_DIR}/data/openvpn/firewall/allowed_networks.conf"
        if ! grep -qxF "${NAT_GATEWAY_NETWORK}" "$allow_file" 2>/dev/null; then
            echo "${NAT_GATEWAY_NETWORK}" >> "$allow_file"
            log_success "Seeded allowed_networks with ${NAT_GATEWAY_NETWORK}"
        fi
    fi

    log_success "Directories created at ${INSTALL_DIR}"
}

generate_certificates() {
    log_info "Generating SSL certificates..."

    # Always generate self-signed first (Traefik fallback cert)
    log_info "Generating self-signed certificates..."

    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout ${INSTALL_DIR}/certs/server.key \
        -out ${INSTALL_DIR}/certs/server.crt \
        -subj "/C=BR/ST=SP/L=SaoPaulo/O=EdgeGate/CN=${DOMAIN}"

    chmod 600 ${INSTALL_DIR}/certs/server.key

    if [ "$USE_LETSENCRYPT" = true ]; then
        touch ${INSTALL_DIR}/certs/.letsencrypt
    fi

    log_success "SSL certificates generated"
}

setup_letsencrypt() {
    if [ "$USE_LETSENCRYPT" != true ]; then
        log_info "Traefik will use self-signed certificate (Let's Encrypt disabled)"
        return 0
    fi

    log_info "Let's Encrypt configured for Traefik..."
    log_info "Traefik will automatically obtain and renew certificates via ACME HTTP-01"
    log_info "ACME email: ${ACME_EMAIL:-${ADMIN_EMAIL}}"
    log_success "Let's Encrypt will be activated when Traefik starts"
}

create_env_file() {
    log_info "Creating environment configuration..."

    # Ensure agent tokens exist even on code paths that didn't pre-generate them.
    UPDATE_AGENT_TOKEN=${UPDATE_AGENT_TOKEN:-$(generate_secret)}

    cat > ${INSTALL_DIR}/config/.env << EOF
# ============================================
# EdgeGate - Configuration
# Generated: $(date -Iseconds)
# ============================================

# ==================== General ====================
PROJECT_NAME="EdgeGate"
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=${SECRET_KEY}
DOMAIN=${DOMAIN}

# ==================== Database ====================
DB_TYPE=${DB_TYPE}
POSTGRES_HOST=${DB_HOST}
POSTGRES_PORT=${DB_PORT}
POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASSWORD}

# ==================== Redis ====================
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD}

# ==================== JWT ====================
JWT_SECRET_KEY=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# ==================== Admin ====================
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_EMAIL=${ADMIN_EMAIL}
INITIAL_ADMIN_PASSWORD=${ADMIN_PASSWORD}
INITIAL_ADMIN_REQUIRE_MFA=true

# ==================== OpenVPN ====================
OPENVPN_HOST=${DOMAIN}
OPENVPN_PORT=${VPN_PORT}
OPENVPN_PROTOCOL=udp
OPENVPN_NETWORK=${VPN_NETWORK}
OPENVPN_NETMASK=${VPN_NETMASK}
OPENVPN_DNS_1=8.8.8.8
OPENVPN_DNS_2=1.1.1.1

# ==================== SSL ====================
USE_LETSENCRYPT=${USE_LETSENCRYPT}
LETSENCRYPT_EMAIL=${ACME_EMAIL:-${ADMIN_EMAIL}}

# ==================== Network ====================
PUBLIC_INTERFACE=${PUBLIC_INTERFACE}
# Private subnet that uses this host as a NAT gateway (empty = disabled)
NAT_GATEWAY_NETWORK=${NAT_GATEWAY_NETWORK}

# ==================== Firewall ====================
FIREWALL_ENGINE=iptables
FIREWALL_DEFAULT_POLICY=drop
ENABLE_IP_FORWARDING=true
ENABLE_NAT=true

# ==================== NAT Agent ====================
NAT_AGENT_TOKEN=${NAT_AGENT_TOKEN}

# ==================== IPsec Agent ====================
IPSEC_AGENT_URL=http://172.17.0.1:8101
IPSEC_AGENT_TOKEN=${IPSEC_AGENT_TOKEN}

# ==================== Update Agent ====================
# Host systemd service reachable from the backend via host-gateway.
UPDATE_AGENT_URL=http://update-agent:8102
UPDATE_AGENT_TOKEN=${UPDATE_AGENT_TOKEN}

# ==================== Traefik ====================
TRAEFIK_ACME_EMAIL=${ACME_EMAIL:-${ADMIN_EMAIL}}

# ==================== Docker ====================
# GID do grupo docker no host (para permissões do socket)
DOCKER_GID=${DOCKER_GID}
EOF

    chmod 600 ${INSTALL_DIR}/config/.env

    # Create symlink in main directory for docker-compose
    ln -sf ${INSTALL_DIR}/config/.env ${INSTALL_DIR}/.env

    log_success "Environment file created"
}

create_docker_compose() {
    log_info "Creating Docker Compose configuration..."

    # Detect server IP for NAT agent
    SERVER_IP=$(ip -4 addr show scope global | grep inet | head -1 | awk '{print $2}' | cut -d/ -f1)
    if [ -z "$SERVER_IP" ]; then
        SERVER_IP="127.0.0.1"
        log_warn "Could not detect server IP, using 127.0.0.1"
    else
        log_info "Detected server IP: $SERVER_IP"
    fi

    # Determine postgres service
    if [ "$DB_TYPE" = "local" ]; then
        POSTGRES_SERVICE="
  postgres:
    image: postgres:17-alpine
    container_name: edgegate-postgres
    restart: unless-stopped
    ports:
      - \"127.0.0.1:5432:5432\"
    environment:
      POSTGRES_DB: \${POSTGRES_DB}
      POSTGRES_USER: \${POSTGRES_USER}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD}
    volumes:
      - ${INSTALL_DIR}/data/postgres:/var/lib/postgresql/data
    networks:
      - edgegate-network
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready -U \${POSTGRES_USER} -d \${POSTGRES_DB}\"]
      interval: 10s
      timeout: 5s
      retries: 5
"
        POSTGRES_DEPENDS="postgres"
        # NAT agent runs in host mode: use localhost to reach Docker postgres
        NAT_POSTGRES_HOST="127.0.0.1"
        NAT_POSTGRES_PORT="5432"
    else
        POSTGRES_SERVICE=""
        POSTGRES_DEPENDS=""
        # NAT agent runs in host mode: use the external DB host/port directly
        NAT_POSTGRES_HOST="${DB_HOST}"
        NAT_POSTGRES_PORT="${DB_PORT}"
    fi

    # Host-based ("secure") traefik routers carry an ACME certresolver only when
    # Let's Encrypt is enabled; otherwise the panel domain uses the self-signed cert.
    if [ "$USE_LETSENCRYPT" = true ]; then
        _LE_BE=$'\n      - "traefik.http.routers.backend-secure.tls.certresolver=letsencrypt"'
        _LE_FE=$'\n      - "traefik.http.routers.frontend-secure.tls.certresolver=letsencrypt"'
    else
        _LE_BE=""
        _LE_FE=""
    fi

    cat > ${INSTALL_DIR}/docker-compose.yml << EOF
services:
${POSTGRES_SERVICE}
  redis:
    image: redis:7-alpine
    container_name: edgegate-redis
    restart: unless-stopped
    command: redis-server --requirepass \${REDIS_PASSWORD}
    volumes:
      - ${INSTALL_DIR}/data/redis:/data
    networks:
      - edgegate-network
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "\${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: edgegate-backend
    restart: unless-stopped
    env_file:
      - .env
    group_add:
      - "${DOCKER_GID}"
    environment:
      - NAT_AGENT_URL=http://${SERVER_IP}:8100
      - NAT_AGENT_TOKEN=\${NAT_AGENT_TOKEN}
      - IPSEC_AGENT_URL=http://${SERVER_IP}:8101
      - IPSEC_AGENT_TOKEN=\${IPSEC_AGENT_TOKEN}
      - UPDATE_AGENT_URL=http://${SERVER_IP}:8102
      - UPDATE_AGENT_TOKEN=\${UPDATE_AGENT_TOKEN}
      - TRAEFIK_DYNAMIC_DIR=/etc/traefik/dynamic
      - TRAEFIK_API_URL=http://traefik:8080
      - TRAEFIK_ACME_EMAIL=\${TRAEFIK_ACME_EMAIL}
      - ACME_STAGING=\${ACME_STAGING:-false}
      - COMPOSE_PROJECT_DIR=${INSTALL_DIR}
    depends_on:
      ${POSTGRES_DEPENDS:+- $POSTGRES_DEPENDS}
      - redis
    labels:
      - "traefik.enable=true"
      - "traefik.http.services.backend.loadbalancer.server.port=8000"
      # Domain (Host-based) router: real cert on the panel domain. certresolver is
      # appended (via \${_LE_BE}) only when Let's Encrypt is enabled. The IP-based
      # fallback routers below keep the panel reachable by public IP (self-signed) so a
      # not-yet-ready domain can never lock you out. Domain routers win on priority.
      - "traefik.http.routers.backend-secure.rule=Host(\`\${DOMAIN}\`) && (PathPrefix(\`/api\`) || PathPrefix(\`/docs\`) || PathPrefix(\`/openapi.json\`) || PathPrefix(\`/health\`))"
      - "traefik.http.routers.backend-secure.entrypoints=websecure"
      - "traefik.http.routers.backend-secure.tls=true"${_LE_BE}
      - "traefik.http.routers.backend-secure.priority=20"
      # HTTPS fallback for IP access (self-signed cert)
      - "traefik.http.routers.backend-ip.rule=PathPrefix(\`/api\`) || PathPrefix(\`/docs\`) || PathPrefix(\`/openapi.json\`) || PathPrefix(\`/health\`)"
      - "traefik.http.routers.backend-ip.entrypoints=websecure"
      - "traefik.http.routers.backend-ip.tls=true"
      - "traefik.http.routers.backend-ip.priority=10"
      # HTTP fallback for IP access (no redirect)
      - "traefik.http.routers.backend-http.rule=PathPrefix(\`/api\`) || PathPrefix(\`/docs\`) || PathPrefix(\`/openapi.json\`) || PathPrefix(\`/health\`)"
      - "traefik.http.routers.backend-http.entrypoints=web"
      - "traefik.http.routers.backend-http.priority=10"
    volumes:
      - ${INSTALL_DIR}/data/openvpn:/etc/openvpn
      - ${INSTALL_DIR}/logs:/var/log/edgegate
      - ${INSTALL_DIR}/data/backend:/app/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${INSTALL_DIR}/docker-compose.yml:/app/docker-compose.yml
      - ${INSTALL_DIR}/VERSION:/app/VERSION:ro
      - traefik_dynamic:/etc/traefik/dynamic
      - traefik_acme:/acme
      - traefik_certs_manual:/certs/manual
    networks:
      - edgegate-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: edgegate-frontend
    restart: unless-stopped
    environment:
      - VITE_API_URL=https://\${DOMAIN}/api
    labels:
      - "traefik.enable=true"
      - "traefik.http.services.frontend.loadbalancer.server.port=80"
      # Domain (Host-based) router: real cert on the panel domain (see backend note).
      - "traefik.http.routers.frontend-secure.rule=Host(\`\${DOMAIN}\`)"
      - "traefik.http.routers.frontend-secure.entrypoints=websecure"
      - "traefik.http.routers.frontend-secure.tls=true"${_LE_FE}
      - "traefik.http.routers.frontend-secure.priority=15"
      # HTTPS fallback for IP access (self-signed cert)
      - "traefik.http.routers.frontend-ip.rule=PathPrefix(\`/\`)"
      - "traefik.http.routers.frontend-ip.entrypoints=websecure"
      - "traefik.http.routers.frontend-ip.tls=true"
      - "traefik.http.routers.frontend-ip.priority=1"
      # HTTP fallback for IP access (no redirect)
      - "traefik.http.routers.frontend-http.rule=PathPrefix(\`/\`)"
      - "traefik.http.routers.frontend-http.entrypoints=web"
      - "traefik.http.routers.frontend-http.priority=1"
    networks:
      - edgegate-network

  openvpn:
    build:
      context: ./docker/openvpn
      dockerfile: Dockerfile
    container_name: edgegate-openvpn
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    ports:
      - "\${OPENVPN_PORT}:1194/udp"
    volumes:
      - ${INSTALL_DIR}/data/openvpn:/etc/openvpn
    networks:
      - edgegate-network
    sysctls:
      - net.ipv4.ip_forward=1

  traefik:
    image: traefik:v3.6
    container_name: edgegate-traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ${INSTALL_DIR}/docker/traefik/traefik.yml:/etc/traefik/traefik.yml:ro
      - ${INSTALL_DIR}/docker/traefik/dynamic/internal.yml:/etc/traefik/dynamic/internal.yml:ro
      # update-agent.yml is NOT bind-mounted: a host bind-mount gets wiped by
      # update.sh --delete, after which Docker recreates the path as a directory,
      # causing a mount-type mismatch that crashes traefik (exit 127) and takes the
      # whole web down. It is seeded into the traefik_dynamic named volume by
      # start_services instead, which survives updates and reboots.
      - traefik_dynamic:/etc/traefik/dynamic
      - traefik_acme:/acme
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${INSTALL_DIR}/certs:/certs:ro
      - traefik_certs_manual:/certs-manual:ro
      - ${INSTALL_DIR}/logs:/var/log/traefik
    environment:
      - TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_EMAIL=\${TRAEFIK_ACME_EMAIL}
    depends_on:
      - backend
      - frontend
    networks:
      - edgegate-network

  nat-agent:
    build:
      context: ./docker/nat-agent
      dockerfile: Dockerfile
    container_name: edgegate-nat-agent
    restart: unless-stopped
    network_mode: host
    privileged: true
    environment:
      - POSTGRES_HOST=${NAT_POSTGRES_HOST}
      - POSTGRES_PORT=${NAT_POSTGRES_PORT}
      - POSTGRES_DB=\${POSTGRES_DB}
      - POSTGRES_USER=\${POSTGRES_USER}
      - POSTGRES_PASSWORD=\${POSTGRES_PASSWORD}
      - NAT_AGENT_TOKEN=\${NAT_AGENT_TOKEN}
      - NAT_GATEWAY_NETWORK=\${NAT_GATEWAY_NETWORK:-}
      - PUBLIC_INTERFACE=\${PUBLIC_INTERFACE:-eth0}

volumes:
  traefik_dynamic:
  traefik_acme:
  traefik_certs_manual:

networks:
  edgegate-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
EOF

    log_success "Docker Compose file created"
}

create_traefik_config() {
    log_info "Creating Traefik configuration..."

    # Traefik configs are already in the docker/ directory from copy_application_files
    # Just verify they exist
    if [ -f "${INSTALL_DIR}/docker/traefik/traefik.yml" ]; then
        log_success "Traefik static configuration found"
    else
        log_error "Traefik static configuration not found at ${INSTALL_DIR}/docker/traefik/traefik.yml"
        exit 1
    fi

    if [ -f "${INSTALL_DIR}/docker/traefik/dynamic/internal.yml" ]; then
        log_success "Traefik dynamic configuration found"
    else
        log_error "Traefik dynamic configuration not found at ${INSTALL_DIR}/docker/traefik/dynamic/internal.yml"
        exit 1
    fi

    # ---- Update Agent route (resilient progress polling) ----
    # Exposes ONLY GET /update-agent/status, forwarded to the host update-agent
    # with the agent token injected by Traefik. This lets the SPA poll update
    # progress even while the backend/frontend containers are being rebuilt.
    # The privileged POST /update stays reachable only via the authenticated
    # backend (admin JWT) — it is intentionally NOT routed here.
    local ua_ip="${SERVER_IP:-$(ip -4 addr show scope global | grep inet | head -1 | awk '{print $2}' | cut -d/ -f1)}"
    ua_ip="${ua_ip:-172.17.0.1}"
    local ua_token="${UPDATE_AGENT_TOKEN}"
    [ -z "$ua_token" ] && [ -f /opt/edgegate/update-agent.token ] && ua_token="$(cat /opt/edgegate/update-agent.token)"

    # Generated to a host staging path. It is no longer bind-mounted into traefik
    # (see the traefik service in the compose file for why); start_services copies
    # this file into the traefik_dynamic named volume once traefik is up.
    cat > "${INSTALL_DIR}/docker/traefik/dynamic/update-agent.yml" << EOF
# Traefik Dynamic Configuration - Update Agent (auto-generated by install.sh)
# Read-only status polling that survives backend/frontend restarts.
http:
  routers:
    update-agent-status:
      rule: "PathPrefix(\`/update-agent/status\`) && Method(\`GET\`)"
      entrypoints: [websecure]
      tls: {}
      priority: 100
      service: update-agent
      middlewares: [update-agent-strip, update-agent-auth]
    update-agent-status-http:
      rule: "PathPrefix(\`/update-agent/status\`) && Method(\`GET\`)"
      entrypoints: [web]
      priority: 100
      service: update-agent
      middlewares: [update-agent-strip, update-agent-auth]
  services:
    update-agent:
      loadBalancer:
        servers:
          - url: "http://${ua_ip}:8102"
  middlewares:
    update-agent-strip:
      stripPrefix:
        prefixes: ["/update-agent"]
    update-agent-auth:
      headers:
        customRequestHeaders:
          Authorization: "Bearer ${ua_token}"
EOF
    chmod 600 "${INSTALL_DIR}/docker/traefik/dynamic/update-agent.yml"
    log_success "Update Agent route configured (${ua_ip}:8102)"

    log_success "Traefik configuration ready"
}

copy_application_files() {
    log_info "Copying application files..."

    # Copy backend
    if [ -d "${SCRIPT_DIR}/backend" ]; then
        cp -r "${SCRIPT_DIR}/backend" ${INSTALL_DIR}/
        log_info "  Copied backend"
    else
        log_error "Backend directory not found at ${SCRIPT_DIR}/backend"
        exit 1
    fi

    # Copy frontend
    if [ -d "${SCRIPT_DIR}/frontend" ]; then
        cp -r "${SCRIPT_DIR}/frontend" ${INSTALL_DIR}/
        log_info "  Copied frontend"
    else
        log_error "Frontend directory not found at ${SCRIPT_DIR}/frontend"
        exit 1
    fi

    # Copy docker configs
    if [ -d "${SCRIPT_DIR}/docker" ]; then
        cp -r "${SCRIPT_DIR}/docker" ${INSTALL_DIR}/
        log_info "  Copied docker configs"
    else
        log_error "Docker directory not found at ${SCRIPT_DIR}/docker"
        exit 1
    fi

    # Copy VERSION file (mounted into backend; source of truth for the UI badge)
    if [ -f "${SCRIPT_DIR}/VERSION" ]; then
        cp "${SCRIPT_DIR}/VERSION" ${INSTALL_DIR}/VERSION
        log_info "  Copied VERSION ($(cat ${SCRIPT_DIR}/VERSION | tr -d '[:space:]'))"
    fi

    log_success "Application files copied"
}

start_services() {
    log_info "Starting services..."

    cd ${INSTALL_DIR}

    # Build and start
    docker compose --env-file ${INSTALL_DIR}/config/.env up -d --build

    log_info "Waiting for services to be healthy..."
    sleep 10

    # Seed the update-agent route into the traefik_dynamic named volume. It is not
    # bind-mounted (a host bind-mount is wiped by update.sh --delete and then breaks
    # the traefik mount), so we copy it into the running container's volume here. The
    # file survives updates/reboots because update.sh does not sync named volumes.
    if [ -f "${INSTALL_DIR}/docker/traefik/dynamic/update-agent.yml" ]; then
        log_info "Seeding update-agent route into traefik_dynamic volume..."
        if docker cp "${INSTALL_DIR}/docker/traefik/dynamic/update-agent.yml" \
            edgegate-traefik:/etc/traefik/dynamic/update-agent.yml >/dev/null 2>&1; then
            log_success "  Update-agent route seeded into the volume"
        else
            log_warn "  Could not seed update-agent route (is traefik running?)"
        fi
    fi

    # Check status
    docker compose ps

    log_success "Services started"
}

fix_permissions() {
    log_info "Fixing permissions and docker socket..."

    cd ${INSTALL_DIR}

    # 1. Fix docker.sock permissions on host
    log_info "  Setting docker.sock permissions..."
    chmod 666 /var/run/docker.sock

    # 2. Fix /app/data permissions via volume
    log_info "  Fixing /app/data permissions..."
    VOLUME_PATH=$(docker volume inspect edgegate_backend_data --format '{{ .Mountpoint }}' 2>/dev/null || echo "")
    if [ -n "$VOLUME_PATH" ] && [ -d "$VOLUME_PATH" ]; then
        chown -R 1000:1000 "$VOLUME_PATH"
        chmod -R 755 "$VOLUME_PATH"
    fi

    # Also fix via container
    docker exec -u root edgegate-backend chown -R vpnuser:vpnuser /app/data 2>/dev/null || true
    docker exec -u root edgegate-backend chmod -R 755 /app/data 2>/dev/null || true

    # 2b. Fix /certs/manual permissions (ACME DNS-01 certificates)
    log_info "  Fixing /certs/manual permissions..."
    docker exec -u root edgegate-backend chown -R vpnuser:vpnuser /certs/manual 2>/dev/null || true

    # 2c. Fix /etc/traefik/dynamic permissions (backend writes routes.yml)
    log_info "  Fixing /etc/traefik/dynamic permissions..."
    docker exec -u root edgegate-backend chown -R vpnuser:vpnuser /etc/traefik/dynamic 2>/dev/null || true

    # 3. Verify docker.sock is accessible
    log_info "  Verifying docker socket access..."
    if docker exec edgegate-backend test -S /var/run/docker.sock 2>/dev/null; then
        log_success "  Docker socket is accessible"
    else
        log_warn "  Docker socket not accessible, recreating backend..."
        docker compose stop backend
        docker compose rm -f backend
        docker compose up -d backend
        sleep 10
    fi

    # 4. Test docker commands
    log_info "  Testing docker commands..."
    if docker exec edgegate-backend docker ps >/dev/null 2>&1; then
        log_success "  Backend can execute docker commands"
    else
        log_warn "  Backend cannot execute docker commands yet"
        log_info "  This is normal, it will work after backend fully starts"
    fi

    # 5. Test file write permissions
    log_info "  Testing file write permissions..."
    if docker exec -u vpnuser edgegate-backend touch /app/data/test.txt 2>/dev/null; then
        docker exec edgegate-backend rm /app/data/test.txt 2>/dev/null
        log_success "  Backend user can write to /app/data"
    else
        log_warn "  Backend user cannot write to /app/data"
    fi

    # 6. Configure UFW for host agents (if UFW is enabled)
    if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
        log_info "  Configuring UFW for host agents..."
        ufw allow from 172.17.0.0/16 to any port 8100 comment 'NAT Agent for Docker' >/dev/null 2>&1 || true
        ufw allow from 172.20.0.0/16 to any port 8100 comment 'NAT Agent for VPN Network' >/dev/null 2>&1 || true
        ufw allow from 172.17.0.0/16 to any port 8102 comment 'Update Agent for Docker' >/dev/null 2>&1 || true
        ufw allow from 172.20.0.0/16 to any port 8102 comment 'Update Agent for VPN Network' >/dev/null 2>&1 || true
        log_success "  UFW configured for host agents"
    fi

    # 7. Create VPN_RULES chain for firewall status (if iptables is available)
    if command -v iptables >/dev/null 2>&1; then
        log_info "  Creating VPN_RULES chain..."
        iptables -N VPN_RULES 2>/dev/null || true  # Ignore if already exists
        log_success "  VPN_RULES chain ready"
    fi

    log_success "Permissions fixed"
}

print_summary() {
    echo
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}║           Installation Complete!                          ║${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo
    echo -e "${CYAN}Access Information:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  Web Panel:     ${YELLOW}https://${DOMAIN}${NC}"
    echo -e "  API Docs:      ${YELLOW}https://${DOMAIN}/docs${NC}"
    echo -e "  VPN Server:    ${YELLOW}${DOMAIN}:${VPN_PORT}/UDP${NC}"
    echo
    echo -e "${CYAN}Admin Credentials:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  Username:      ${YELLOW}admin${NC}"
    echo -e "  Password:      ${YELLOW}${ADMIN_PASSWORD}${NC}"
    echo
    echo -e "${RED}⚠  IMPORTANT: Save these credentials securely!${NC}"
    echo -e "${RED}⚠  Change the admin password after first login!${NC}"
    echo
    echo -e "${CYAN}Useful Commands:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  View logs:     cd ${INSTALL_DIR} && docker compose logs -f"
    echo "  Restart:       cd ${INSTALL_DIR} && docker compose restart"
    echo "  Stop:          cd ${INSTALL_DIR} && docker compose down"
    echo "  Update:        cd ${INSTALL_DIR} && docker compose pull && docker compose up -d"
    echo
    echo -e "${CYAN}Configuration:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Install dir:   ${INSTALL_DIR}"
    echo "  Config file:   ${INSTALL_DIR}/config/.env"
    echo "  Data dir:      ${INSTALL_DIR}/data"
    echo "  Logs dir:      ${INSTALL_DIR}/logs"
    echo
    echo -e "${CYAN}IPsec (Site-to-Site VPN):${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  MSS Clamping:  /etc/ipsec.d/mss-clamp.sh (auto on tunnel up/down)"
    echo "  IP Forward:    enabled (net.ipv4.ip_forward=1)"
    echo "  rp_filter:     disabled (required for IPsec routing)"
    echo "  UFW routes:    auto-configured per tunnel via leftupdown"
    echo
    echo -e "${YELLOW}AWS EC2 - Required manual steps for IPsec:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  1. Disable Source/Destination Check on the gateway EC2 instance:"
    echo "     EC2 Console > Instance > Actions > Networking > Change source/dest check > Stop"
    echo "  2. Add Security Group inbound rules for the remote VPN subnet:"
    echo "     Allow traffic from remote_subnet CIDR (e.g. 192.168.0.0/24)"
    echo "     Ports: as needed (RDP 3389, SSH 22, ICMP, etc.)"
    echo
}

# ==================== Upgrade Functions ====================

detect_existing_installation() {
    # Check if there's an existing installation
    if [ -f "${INSTALL_DIR}/.env" ] && ( [ -f "${INSTALL_DIR}/docker-compose.prod.yml" ] || [ -f "${INSTALL_DIR}/docker-compose.yml" ] ); then
        return 0  # Installation exists
    fi
    return 1  # No installation found
}

run_upgrade_steps() {
    # Ensure rsync is available (used for file sync)
    if ! command -v rsync &> /dev/null; then
        log_info "Installing rsync..."
        apt-get update -qq && apt-get install -y -qq rsync
    fi

    # Load existing environment
    if [ -f "${INSTALL_DIR}/.env" ]; then
        log_info "Loading existing configuration..."
        set -a
        source "${INSTALL_DIR}/.env"
        set +a
    fi

    # Backup current .env
    log_info "Creating backup of configuration..."
    cp "${INSTALL_DIR}/.env" "${INSTALL_DIR}/.env.backup.$(date +%Y%m%d_%H%M%S)"
    log_success "Backup created"

    # Optional database backup
    if wt_yesno "Database Backup" \
        "Create a database backup before upgrading?\n\nRecommended if you have important data." \
        "default_yes" "CREATE_BACKUP"; then
        log_info "Creating database backup..."
        cd "${INSTALL_DIR}"
        docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-edgegate_admin}" "${POSTGRES_DB:-edgegate}" > "backup_$(date +%Y%m%d_%H%M%S).sql" 2>/dev/null || {
            log_warn "Database backup failed (containers may not be running)"
        }
    fi

    # Run upgrade with progress gauge
    local UPGRADE_LOG="/tmp/vpn-upgrade-$$.log"
    local UPGRADE_ERR="/tmp/vpn-upgrade-$$.err"
    rm -f "$UPGRADE_ERR"
    if $INTERACTIVE; then
        (
            set +e  # Disable errexit inside subshell - gauge pipe masks errors
            run_step() {
                local pct=$1 msg=$2
                shift 2
                echo "$pct"; echo "XXX"; echo "$msg"; echo "XXX"
                if ! "$@" >>"$UPGRADE_LOG" 2>&1; then
                    echo "$msg" > "$UPGRADE_ERR"
                    echo "100"; echo "XXX"; echo "Failed: $msg"; echo "XXX"
                    exit 1
                fi
            }
            echo 5; echo "XXX"; echo "Stopping services..."; echo "XXX"
            cd "${INSTALL_DIR}" && docker compose down >>"$UPGRADE_LOG" 2>&1 || true
            echo 15; echo "XXX"; echo "Updating frontend files..."; echo "XXX"
            rsync -a --delete --exclude='node_modules' --exclude='dist' --exclude='.next' "${SCRIPT_DIR}/frontend/" "${INSTALL_DIR}/frontend/" >>"$UPGRADE_LOG" 2>&1
            echo 25; echo "XXX"; echo "Updating backend files..."; echo "XXX"
            rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' "${SCRIPT_DIR}/backend/" "${INSTALL_DIR}/backend/" >>"$UPGRADE_LOG" 2>&1
            echo 30; echo "XXX"; echo "Updating docker configs..."; echo "XXX"
            rsync -a --delete "${SCRIPT_DIR}/docker/" "${INSTALL_DIR}/docker/" >>"$UPGRADE_LOG" 2>&1
            [ -f "${SCRIPT_DIR}/VERSION" ] && cp "${SCRIPT_DIR}/VERSION" "${INSTALL_DIR}/VERSION"
            run_step 35 "Updating Traefik configuration..." create_traefik_config
            run_step 40 "Updating StrongSwan..." install_strongswan
            run_step 45 "Configuring IPsec sysctl..." configure_ipsec_sysctl
            echo 50; echo "XXX"; echo "Updating IPsec Agent..."; echo "XXX"
            IPSEC_AGENT_DIR="/opt/edgegate/ipsec-agent"
            if [ -d "$IPSEC_AGENT_DIR" ]; then
                cp "${SCRIPT_DIR}/docker/ipsec-agent/app.py" "$IPSEC_AGENT_DIR/" >>"$UPGRADE_LOG" 2>&1
                cp "${SCRIPT_DIR}/docker/ipsec-agent/requirements.txt" "$IPSEC_AGENT_DIR/" >>"$UPGRADE_LOG" 2>&1
                source "$IPSEC_AGENT_DIR/venv/bin/activate"
                pip install -r "$IPSEC_AGENT_DIR/requirements.txt" -q >>"$UPGRADE_LOG" 2>&1
                deactivate
                systemctl restart ipsec-agent >>"$UPGRADE_LOG" 2>&1 || true
            else
                if [ -z "$IPSEC_AGENT_TOKEN" ]; then
                    IPSEC_AGENT_TOKEN=$(generate_secret)
                fi
                install_ipsec_agent >>"$UPGRADE_LOG" 2>&1
            fi
            echo 52; echo "XXX"; echo "Updating Update Agent..."; echo "XXX"
            # Preserve the existing token so the backend's configured token stays valid.
            [ -f /opt/edgegate/update-agent.token ] && UPDATE_AGENT_TOKEN=$(cat /opt/edgegate/update-agent.token)
            install_update_agent >>"$UPGRADE_LOG" 2>&1 || true
            echo 60; echo "XXX"; echo "Rebuilding Docker images (this may take a few minutes)..."; echo "XXX"
            cd "${INSTALL_DIR}" && docker compose build --no-cache nat-agent backend frontend openvpn >>"$UPGRADE_LOG" 2>&1
            run_step 80 "Fixing permissions..." fix_permissions
            echo 85; echo "XXX"; echo "Starting services..."; echo "XXX"
            docker compose up -d >>"$UPGRADE_LOG" 2>&1
            echo 90; echo "XXX"; echo "Waiting for services to be healthy..."; echo "XXX"
            local max_attempts=30
            local attempt=0
            while [ $attempt -lt $max_attempts ]; do
                if curl -sf http://localhost/health > /dev/null 2>&1; then
                    break
                fi
                attempt=$((attempt + 1))
                sleep 2
            done
            echo 100; echo "XXX"; echo "Upgrade complete!"; echo "XXX"
        ) | wt_gauge "Upgrading EdgeGate" "Starting upgrade..."

        # Check if subshell failed via sentinel file
        if [ -f "$UPGRADE_ERR" ]; then
            local failed_step
            failed_step=$(cat "$UPGRADE_ERR")
            whiptail --title "Upgrade Error" --msgbox "Upgrade failed at:\n$failed_step\n\nCheck the log file: $UPGRADE_LOG" 12 $WT_WIDTH
            rm -f "$UPGRADE_ERR"
            exit 1
        fi
        rm -f "$UPGRADE_ERR"
    else
        # Non-interactive upgrade (same steps, with log output)
        log_info "Stopping services..."
        cd "${INSTALL_DIR}"
        docker compose down
        log_success "Services stopped"

        log_info "Updating application files..."
        rsync -a --delete --exclude='node_modules' --exclude='dist' --exclude='.next' "${SCRIPT_DIR}/frontend/" "${INSTALL_DIR}/frontend/"
        rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' "${SCRIPT_DIR}/backend/" "${INSTALL_DIR}/backend/"
        rsync -a --delete "${SCRIPT_DIR}/docker/" "${INSTALL_DIR}/docker/"
        [ -f "${SCRIPT_DIR}/VERSION" ] && cp "${SCRIPT_DIR}/VERSION" "${INSTALL_DIR}/VERSION"
        log_success "Files updated"

        log_info "Updating Traefik configuration..."
        create_traefik_config
        log_success "Traefik configuration updated"

        log_info "Updating StrongSwan and IPsec Agent..."
        install_strongswan
        configure_ipsec_sysctl

        IPSEC_AGENT_DIR="/opt/edgegate/ipsec-agent"
        if [ -d "$IPSEC_AGENT_DIR" ]; then
            cp "${SCRIPT_DIR}/docker/ipsec-agent/app.py" "$IPSEC_AGENT_DIR/"
            cp "${SCRIPT_DIR}/docker/ipsec-agent/requirements.txt" "$IPSEC_AGENT_DIR/"
            source "$IPSEC_AGENT_DIR/venv/bin/activate"
            pip install -r "$IPSEC_AGENT_DIR/requirements.txt" -q
            deactivate
            systemctl restart ipsec-agent
            log_success "IPsec Agent updated"
        else
            if [ -z "$IPSEC_AGENT_TOKEN" ]; then
                IPSEC_AGENT_TOKEN=$(generate_secret)
            fi
            install_ipsec_agent
        fi

        log_info "Updating Update Agent..."
        [ -f /opt/edgegate/update-agent.token ] && UPDATE_AGENT_TOKEN=$(cat /opt/edgegate/update-agent.token)
        install_update_agent || log_warn "Update Agent update failed"

        log_info "Rebuilding Docker images..."
        cd "${INSTALL_DIR}"
        docker compose build --no-cache nat-agent backend frontend openvpn
        log_success "Images rebuilt"

        log_info "Fixing permissions..."
        fix_permissions
        log_success "Permissions fixed"

        log_info "Starting services..."
        docker compose up -d
        log_success "Services started"

        log_info "Verifying services are healthy..."
        local max_attempts=30
        local attempt=0
        while [ $attempt -lt $max_attempts ]; do
            if curl -sf http://localhost/health > /dev/null 2>&1; then
                log_success "Backend health check passed"
                break
            fi
            attempt=$((attempt + 1))
            sleep 2
        done

        if [ $attempt -eq $max_attempts ]; then
            log_warn "Backend health check timed out - please check logs with: docker compose logs backend"
        fi
    fi
}

perform_upgrade() {
    if ! wt_yesno "Upgrade" \
        "This will upgrade your EdgeGate to the latest version.\n\nYour data and configuration will be preserved.\n\nContinue with upgrade?" \
        "default_yes"; then
        log_info "Upgrade cancelled"
        exit 0
    fi

    run_upgrade_steps

    # Show container status
    log_info "Container status:"
    cd "${INSTALL_DIR}" && docker compose ps

    local upgrade_msg="Upgrade completed successfully!\n\nYour EdgeGate has been upgraded.\n\nConfiguration backup: ${INSTALL_DIR}/.env.backup.*"
    wt_msgbox "Upgrade Complete" "$upgrade_msg"

    echo
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}║              Upgrade completed successfully!              ║${NC}"
    echo -e "${GREEN}║                                                           ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo
    log_info "Your EdgeGate has been upgraded"
    log_info "Configuration backup: ${INSTALL_DIR}/.env.backup.*"
    echo
}

# ==================== Main ====================

# ---- Non-interactive progress bar (clean output; verbose captured to a log) ----
NONINT_LOG="/var/log/vpn-install.log"

nonint_bar() {
    local pct=$1 label=$2 width=32
    local filled=$(( pct * width / 100 ))
    local bar empty
    bar=$(printf '%*s' "$filled" '' | tr ' ' '#')
    empty=$(printf '%*s' "$(( width - filled ))" '')
    printf '\r  [%s%s] %3d%%  %-38.38s' "$bar" "$empty" "$pct" "$label"
}

# run_quiet <pct> <label> <cmd...> — draw the bar, run cmd with output sent to the
# log; on failure show the tail so the error isn't swallowed.
run_quiet() {
    local pct=$1 label=$2; shift 2
    nonint_bar "$pct" "$label"
    if ! "$@" >>"$NONINT_LOG" 2>&1; then
        printf '\n'
        log_error "Failed at: $label"
        echo "  --- last 25 lines of $NONINT_LOG ---"
        tail -n 25 "$NONINT_LOG" 2>/dev/null
        exit 1
    fi
}

run_fresh_install_steps() {
    # Run all installation steps, with progress gauge in interactive mode
    local INSTALL_LOG="/tmp/vpn-install-$$.log"
    local INSTALL_ERR="/tmp/vpn-install-$$.err"
    rm -f "$INSTALL_ERR"
    if $INTERACTIVE; then
        (
            set +e  # Disable errexit inside subshell - gauge pipe masks errors
            run_step() {
                local pct=$1 msg=$2
                shift 2
                echo "$pct"; echo "XXX"; echo "$msg"; echo "XXX"
                if ! "$@" >>"$INSTALL_LOG" 2>&1; then
                    echo "$msg" > "$INSTALL_ERR"
                    echo "100"; echo "XXX"; echo "Failed: $msg"; echo "XXX"
                    exit 1
                fi
            }
            run_step 5  "Installing system dependencies..." install_dependencies
            run_step 15 "Installing StrongSwan (IPsec)..." install_strongswan
            run_step 25 "Installing Docker..." install_docker
            run_step 35 "Configuring firewall..." configure_firewall
            run_step 40 "Creating directory structure..." create_directory_structure
            run_step 45 "Generating SSL certificates..." generate_certificates
            echo 50; echo "XXX"; echo "Detecting Docker socket GID..."; echo "XXX"
            DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null)
            if [ -z "$DOCKER_GID" ] || [ "$DOCKER_GID" = "0" ]; then
                DOCKER_GID="988"
            fi
            run_step 55 "Creating environment configuration..." create_env_file
            run_step 60 "Creating Docker Compose configuration..." create_docker_compose
            run_step 65 "Copying application files..." copy_application_files
            run_step 70 "Configuring Traefik..." create_traefik_config
            run_step 75 "Installing IPsec Agent..." install_ipsec_agent
            run_step 78 "Installing Update Agent..." install_update_agent
            run_step 85 "Building and starting services (this may take a few minutes)..." start_services
            run_step 95 "Fixing permissions..." fix_permissions
            setup_letsencrypt >>"$INSTALL_LOG" 2>&1 || true
            echo 100; echo "XXX"; echo "Installation complete!"; echo "XXX"
        ) | wt_gauge "Installing EdgeGate" "Starting installation..."

        # Check if subshell failed via sentinel file
        if [ -f "$INSTALL_ERR" ]; then
            local failed_step
            failed_step=$(cat "$INSTALL_ERR")
            whiptail --title "Installation Error" --msgbox "Installation failed at:\n$failed_step\n\nCheck the log file: $INSTALL_LOG" 12 $WT_WIDTH
            rm -f "$INSTALL_ERR"
            exit 1
        fi
        rm -f "$INSTALL_ERR"
    else
        # Non-interactive: show a clean progress bar; capture verbose output to a
        # log. Keep apt/needrestart fully quiet and non-blocking.
        : > "$NONINT_LOG" 2>/dev/null || NONINT_LOG="/tmp/vpn-install-$$.log"
        export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
        echo "Installing EdgeGate  (full log: $NONINT_LOG)"

        run_quiet 5   "Installing system dependencies" install_dependencies
        run_quiet 15  "Installing StrongSwan (IPsec)"  install_strongswan
        run_quiet 25  "Installing Docker"              install_docker
        run_quiet 35  "Configuring firewall"           configure_firewall
        run_quiet 42  "Creating directory structure"   create_directory_structure
        run_quiet 48  "Generating SSL certificates"    generate_certificates

        # Detect Docker socket GID for backend container permissions
        DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null)
        if [ -z "$DOCKER_GID" ] || [ "$DOCKER_GID" = "0" ]; then
            DOCKER_GID="988"
        fi

        run_quiet 55  "Creating environment config"    create_env_file
        run_quiet 60  "Creating Docker Compose config"  create_docker_compose
        run_quiet 65  "Copying application files"       copy_application_files
        run_quiet 70  "Configuring Traefik"             create_traefik_config
        run_quiet 75  "Installing IPsec Agent"          install_ipsec_agent
        run_quiet 80  "Installing Update Agent"         install_update_agent
        run_quiet 92  "Building & starting services"    start_services
        run_quiet 96  "Fixing permissions"              fix_permissions
        run_quiet 99  "Configuring SSL"                 setup_letsencrypt
        nonint_bar 100 "Done"; printf '\n'
    fi
}

main() {
    print_banner

    check_root
    check_ubuntu

    # Detect existing installation and ask what to do
    if detect_existing_installation; then
        local INSTALL_ACTION=""
        # NOTE: "upgrade" is listed FIRST on purpose — in non-interactive mode
        # wt_menu picks the first option, so the safe, data-preserving action is
        # the default. A destructive fresh reinstall must be opted into explicitly
        # (interactively, or via INSTALL_ACTION=fresh).
        wt_menu INSTALL_ACTION \
            "Existing Installation Detected" \
            "An existing installation was found at ${INSTALL_DIR}.\nWhat would you like to do?" \
            "upgrade" "Upgrade existing installation (preserves data)" \
            "fresh"   "Fresh install (delete existing and start clean)"

        if [ "$INSTALL_ACTION" = "upgrade" ]; then
            perform_upgrade
            exit 0
        else
            log_info "Removing existing installation..."
            # Stop containers and remove volumes
            cd "${INSTALL_DIR}" && docker compose down -v 2>/dev/null || true
            # Remove existing installation directory
            rm -rf "${INSTALL_DIR}"
            log_success "Existing installation removed"
        fi
    else
        wt_msgbox "Welcome" "EdgeGate Installer v${APP_VERSION}\n\nThis wizard will guide you through the installation\nof the EdgeGate.\n\nYou will need:\n  - A domain name pointing to this server\n  - Root access (already verified)\n\nPress OK to continue."
    fi

    # ---- Domain ----
    while true; do
        wt_input DOMAIN "Domain Configuration" \
            "Enter the domain name for the web panel.\n\nThis domain must point to this server's IP address.\n\nExample: vpn.example.com" ""
        if [ -z "$DOMAIN" ]; then
            if $INTERACTIVE; then
                whiptail --title "Error" --msgbox "Domain is required." 8 $WT_WIDTH
                unset DOMAIN
                continue
            else
                log_error "DOMAIN is required in non-interactive mode"
                exit 1
            fi
        fi
        if validate_domain "$DOMAIN"; then
            break
        else
            if $INTERACTIVE; then
                whiptail --title "Error" --msgbox "Invalid domain format: $DOMAIN\n\nPlease enter a valid domain (e.g., vpn.example.com)" 10 $WT_WIDTH
                unset DOMAIN
            else
                log_error "Invalid domain format: $DOMAIN"
                exit 1
            fi
        fi
    done

    # ---- Database ----
    wt_menu DB_TYPE "Database Configuration" \
        "Choose where to run PostgreSQL:" \
        "local"    "Local - PostgreSQL in Docker (recommended)" \
        "external" "External - Use an existing PostgreSQL server"

    if [ "$DB_TYPE" = "external" ]; then
        wt_input DB_HOST "External Database" "PostgreSQL host:" ""
        wt_input DB_PORT "External Database" "PostgreSQL port:" "5432"
        wt_input DB_NAME "External Database" "Database name:" "edgegate"
        wt_input DB_USER "External Database" "Database user:" "edgegate_admin"
        wt_password DB_PASSWORD "External Database" "Database password:"
    else
        DB_TYPE="local"
        DB_HOST="postgres"
        DB_PORT="5432"
        DB_NAME="edgegate"
        DB_USER="edgegate_admin"
        DB_PASSWORD=$(generate_password)
    fi

    # ---- Admin Password ----
    local ADMIN_PW_MODE=""
    if [ -n "$ADMIN_PASSWORD" ]; then
        # Already set via env var
        ADMIN_PW_MODE="manual"
    else
        wt_menu ADMIN_PW_MODE "Admin Password" \
            "Choose how to set the admin password:" \
            "generate" "Generate automatically (recommended)" \
            "manual"   "Enter password manually"
    fi

    if [ "$ADMIN_PW_MODE" = "manual" ] && [ -z "$ADMIN_PASSWORD" ]; then
        while true; do
            wt_password ADMIN_PASSWORD "Admin Password" \
                "Enter admin password (minimum 12 characters):"
            if [ ${#ADMIN_PASSWORD} -ge 12 ]; then
                break
            else
                if $INTERACTIVE; then
                    whiptail --title "Error" --msgbox "Password must be at least 12 characters.\nYou entered ${#ADMIN_PASSWORD} characters." 8 $WT_WIDTH
                    unset ADMIN_PASSWORD
                else
                    log_error "Admin password must be at least 12 characters"
                    exit 1
                fi
            fi
        done
    elif [ "$ADMIN_PW_MODE" = "generate" ]; then
        ADMIN_PASSWORD=$(generate_password)
    fi

    # ---- VPN Configuration ----
    wt_input VPN_NETWORK "VPN Configuration" "VPN network address:" "$DEFAULT_VPN_NETWORK"
    wt_input VPN_NETMASK "VPN Configuration" "VPN netmask:" "$DEFAULT_VPN_NETMASK"
    wt_input VPN_PORT    "VPN Configuration" "VPN port (UDP):" "$DEFAULT_VPN_PORT"

    # ---- Network / NAT gateway ----
    wt_input PUBLIC_INTERFACE "Network" \
        "Public uplink interface (toward the internet):" "$DEFAULT_PUBLIC_INTERFACE"
    wt_input NAT_GATEWAY_NETWORK "Network" \
        "Private subnet that uses this host as a NAT gateway (CIDR, e.g. 10.48.0.0/16).\nLeave EMPTY to disable." \
        "$DEFAULT_NAT_GATEWAY_NETWORK" optional

    # ---- SSL / Let's Encrypt ----
    if wt_yesno "SSL Configuration" \
        "Use Let's Encrypt for free SSL certificates?\n\nRequires:\n  - Domain pointing to this server\n  - Ports 80/443 accessible from internet\n\nIf 'No', a self-signed certificate will be used." \
        "default_no" "USE_LETSENCRYPT"; then
        USE_LETSENCRYPT=true
        while true; do
            wt_input ACME_EMAIL "Let's Encrypt" \
                "Enter email for Let's Encrypt notifications.\nYou'll receive certificate expiry warnings." \
                "admin@${DOMAIN}"
            if validate_email "$ACME_EMAIL"; then
                break
            else
                if $INTERACTIVE; then
                    whiptail --title "Error" --msgbox "Invalid email format: $ACME_EMAIL" 8 $WT_WIDTH
                    unset ACME_EMAIL
                else
                    log_error "Invalid email format: $ACME_EMAIL"
                    exit 1
                fi
            fi
        done
    else
        USE_LETSENCRYPT=false
        ACME_EMAIL=""
    fi

    # ---- Generate Secrets ----
    SECRET_KEY=$(generate_secret)
    JWT_SECRET=$(generate_secret)
    REDIS_PASSWORD=$(generate_password)
    NAT_AGENT_TOKEN=$(generate_secret)
    IPSEC_AGENT_TOKEN=$(generate_secret)
    UPDATE_AGENT_TOKEN=$(generate_secret)
    ADMIN_EMAIL="admin@${DOMAIN}"

    # ---- Configuration Summary ----
    local ssl_text
    if [ "$USE_LETSENCRYPT" = true ]; then
        ssl_text="Let's Encrypt ($ACME_EMAIL)"
    else
        ssl_text="Self-signed certificate"
    fi

    local summary="Domain:         $DOMAIN
Database:       $DB_TYPE ($DB_HOST:$DB_PORT)
VPN Network:    $VPN_NETWORK/$VPN_NETMASK
VPN Port:       $VPN_PORT/UDP
SSL:            $ssl_text"

    wt_msgbox "Configuration Summary" "$summary"

    # ---- Confirm Installation ----
    if ! wt_yesno "Confirm Installation" "All settings are configured.\n\nProceed with installation?" "default_yes"; then
        log_warn "Installation cancelled"
        exit 0
    fi

    # ---- Run Installation ----
    run_fresh_install_steps

    # ---- Completion ----
    local complete_msg="Installation Complete!

Access Information:
  Web Panel:     https://${DOMAIN}
  API Docs:      https://${DOMAIN}/docs
  VPN Server:    ${DOMAIN}:${VPN_PORT}/UDP

Admin Credentials:
  Username:      admin
  Password:      ${ADMIN_PASSWORD}

IMPORTANT: Save these credentials securely!
Change the admin password after first login.

Config file:   ${INSTALL_DIR}/config/.env
Logs:          cd ${INSTALL_DIR} && docker compose logs -f"

    if $INTERACTIVE; then
        whiptail --title "Installation Complete" --msgbox "$complete_msg" 24 $WT_WIDTH
    fi

    # Always print to terminal as well (credentials reference)
    print_summary
}

# Run main
main "$@"
