#!/usr/bin/env bash
# EdgeGate — GATE DE RELEASE (Linux / CI / Git Bash).
#
# Sobe uma cópia EFÊMERA da aplicação (banco limpo), roda o smoke E2E do
# Playwright contra ela e derruba tudo no final — mesmo se os testes falharem.
#
#   ./scripts/e2e.sh
#
# Requer: Docker + Compose v2 e o stack de DEV desligado (usa a porta 443).
# Exit 0 = tudo passou · != 0 = build/subida/teste falhou.
set -euo pipefail

PROJECT=edgegate-e2e
BASE_URL="${E2E_BASE_URL:-https://localhost}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.e2e.yml)

# Docker acessível? (antes do trap: se não estiver, não há o que limpar)
if ! docker info >/dev/null 2>&1; then
  echo "[e2e] Docker não está acessível. Inicie o Docker Desktop e tente de novo." >&2
  exit 1
fi

cleanup() {
  echo ""
  echo "[e2e] derrubando stack efêmero ($PROJECT) + volumes..."
  "${COMPOSE[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

# Pré-voo: stack de dev não pode estar ocupando a 443.
if docker ps --filter 'name=edgegate-traefik' --filter 'status=running' --format '{{.Names}}' \
     | grep -qx edgegate-traefik; then
  echo "[e2e] Stack de dev no ar (edgegate-traefik). Derrube antes: docker compose down" >&2
  exit 1
fi

echo "[e2e] build + up (app-tier: postgres redis backend frontend traefik)..."
"${COMPOSE[@]}" up -d --build postgres redis backend frontend traefik

echo "[e2e] aguardando backend em $BASE_URL/health ..."
ready=0
for _ in $(seq 1 60); do
  if curl -ksf "$BASE_URL/health" >/dev/null 2>&1; then ready=1; break; fi
  sleep 3
done
if [ "$ready" -ne 1 ]; then
  "${COMPOSE[@]}" logs --tail 60 backend || true
  echo "[e2e] backend não ficou saudável a tempo" >&2
  exit 1
fi
echo "[e2e] backend OK. Rodando Playwright..."

cd frontend
E2E_BASE_URL="$BASE_URL" npm run test:e2e
echo "[e2e] OK — todos os testes passaram."
