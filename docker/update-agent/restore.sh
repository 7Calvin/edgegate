#!/bin/bash
#
# restore.sh - Restore a full backup (DB + OpenVPN PKI + config) on the HOST.
#
# Launched detached by the update-agent (like update.sh) so it survives the backend
# being recreated. Name-agnostic: reads POSTGRES_USER/DB from .env, loads the dump
# with the schema wiped first, and untars the OpenVPN PKI back into the volume.
# Progress is written to $STATE_DIR/status.json (the same file the updater uses), so
# the UI's existing progress polling covers restore too.
#
set -uo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/edgegate}"
COMPOSE_FILE="${COMPOSE_FILE:-${INSTALL_DIR}/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-${INSTALL_DIR}/config/.env}"
STATE_DIR="${STATE_DIR:-/var/lib/edgegate-update}"
STATUS_FILE="${STATE_DIR}/status.json"
LOG_FILE="${STATE_DIR}/update.log"
LOCK_FILE="${STATE_DIR}/update.lock"
HEALTH_URL="${HEALTH_URL:-http://localhost/health}"
RESTORE_FILE="${RESTORE_FILE:?RESTORE_FILE is required}"
JOB_ID="${JOB_ID:-restore-$(date -u +%Y%m%d%H%M%S)}"

mkdir -p "$STATE_DIR"
compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# write_status <pct> <state> <message> [error]
write_status() {
    local pct="$1" state="$2" msg; msg="$(_esc "$3")"
    local err; err="$(_esc "${4:-}")"
    cat > "${STATUS_FILE}.tmp" <<EOF
{
  "job_id": "$(_esc "$JOB_ID")",
  "state": "$state",
  "pct": $pct,
  "message": "$msg",
  "error": "$err",
  "ref": "restore",
  "updated_at": "$(date -u +%FT%TZ)"
}
EOF
    mv -f "${STATUS_FILE}.tmp" "$STATUS_FILE"
    echo "[$(date -u +%T)] ${pct}% ${state}: $3${4:+ | ERROR: $4}" >> "$LOG_FILE"
}
fail() { write_status "${1:-100}" "failed" "${2:-Restore failed}" "${3:-}"; exit 1; }

# Single-instance lock — shared with update.sh so restore/update can't overlap.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then echo "Another operation is already running" >&2; exit 3; fi

: > "$LOG_FILE"
write_status 2 "running" "Starting restore (job $JOB_ID)"

[ -f "$RESTORE_FILE" ] || fail 2 "backup file not found: $RESTORE_FILE"
command -v docker >/dev/null 2>&1 || fail 2 "docker not found on host"

_envval() { grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }
pg_user="$(_envval POSTGRES_USER)"; pg_user="${pg_user:-edgegate_admin}"
pg_db="$(_envval POSTGRES_DB)";     pg_db="${pg_db:-edgegate}"

write_status 8 "running" "Extracting backup..."
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar -xzf "$RESTORE_FILE" -C "$TMP" >> "$LOG_FILE" 2>&1 || fail 8 "could not extract backup archive"
SRC="$TMP/$(ls "$TMP" | head -n1)"
DB_SQL="${SRC}/db.sql"; [ -f "$DB_SQL" ] || DB_SQL="${SRC}/database.sql"

cd "$INSTALL_DIR" || fail 8 "cannot enter install dir"

write_status 15 "running" "Starting database..."
compose up -d postgres >> "$LOG_FILE" 2>&1
for _ in $(seq 1 30); do
    compose exec -T postgres pg_isready -U "$pg_user" -d "$pg_db" >/dev/null 2>&1 && break
    sleep 2
done

# Stop services that hold DB connections so DROP SCHEMA runs cleanly.
compose stop backend nat-agent >> "$LOG_FILE" 2>&1 || true

if [ -f "$DB_SQL" ]; then
    write_status 35 "running" "Restoring database (${pg_db})..."
    compose exec -T postgres psql -U "$pg_user" -d "$pg_db" \
        -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' >> "$LOG_FILE" 2>&1
    if ! compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$pg_user" -d "$pg_db" < "$DB_SQL" >> "$LOG_FILE" 2>&1; then
        fail 35 "database restore failed (see log)"
    fi
else
    write_status 35 "running" "No database dump in backup — skipping DB restore"
fi

write_status 60 "running" "Starting services..."
compose up -d >> "$LOG_FILE" 2>&1

if [ -f "${SRC}/openvpn-pki.tar.gz" ]; then
    write_status 72 "running" "Restoring OpenVPN PKI/certs..."
    for _ in $(seq 1 15); do compose exec -T openvpn true 2>/dev/null && break; sleep 2; done
    if compose exec -T openvpn tar -xzf - -C /etc/openvpn < "${SRC}/openvpn-pki.tar.gz" >> "$LOG_FILE" 2>&1; then
        compose restart openvpn >> "$LOG_FILE" 2>&1 || true
    else
        echo "WARN: OpenVPN PKI restore had issues" >> "$LOG_FILE"
    fi
fi

write_status 85 "running" "Applying database migrations..."
for _ in $(seq 1 30); do
    compose exec -T backend sh -c 'command -v alembic' >/dev/null 2>&1 && break
    sleep 2
done
compose exec -T backend alembic upgrade head >> "$LOG_FILE" 2>&1 || echo "WARN: alembic upgrade failed" >> "$LOG_FILE"

write_status 92 "running" "Waiting for services to become healthy..."
ok=0; deadline=$(( $(date +%s) + 120 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && { ok=1; break; }
    sleep 3
done
[ "$ok" = "1" ] || fail 92 "unhealthy after restore — check ${LOG_FILE}"

write_status 100 "done" "Restore complete — services healthy"
exit 0
