#!/usr/bin/env pwsh
# EdgeGate — GATE DE RELEASE (Windows / PowerShell 7+).
#
# Sobe uma cópia EFÊMERA da aplicação (banco limpo), roda o smoke E2E do
# Playwright contra ela e derruba tudo no final — mesmo se os testes falharem.
# É o "validar um build candidato antes de lançar".
#
#   pwsh scripts/e2e.ps1
#
# Requer: Docker Desktop e o stack de DEV desligado (ele usa a porta 443).
# Exit 0 = tudo passou · != 0 = build/subida/teste falhou.

$ErrorActionPreference = 'Stop'
$Project = 'edgegate-e2e'
$BaseUrl = if ($env:E2E_BASE_URL) { $env:E2E_BASE_URL } else { 'https://localhost' }
$Compose = @('compose', '-p', $Project,
             '-f', 'docker-compose.yml', '-f', 'docker-compose.e2e.yml')

# Roda a partir da raiz do repo (pasta-pai deste script).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Cleanup {
    Write-Host "`n[e2e] derrubando stack efêmero ($Project) + volumes..." -ForegroundColor Cyan
    docker @Compose down -v --remove-orphans 2>&1 | Out-Host
}

# Docker acessível? (antes de qualquer coisa: se não estiver, não há o que limpar)
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker não está acessível. Inicie o Docker Desktop e tente de novo."
    exit 1
}

# Pré-voo: o stack de dev não pode estar ocupando a 443.
$devTraefik = docker ps --filter 'name=edgegate-traefik' --filter 'status=running' --format '{{.Names}}'
if ($devTraefik -contains 'edgegate-traefik') {
    Write-Error "Stack de dev no ar (edgegate-traefik). Derrube antes: docker compose down"
    exit 1
}

$failed = $false
try {
    Write-Host "[e2e] build + up (app-tier: postgres redis backend frontend traefik)..." -ForegroundColor Cyan
    docker @Compose up -d --build postgres redis backend frontend traefik
    if ($LASTEXITCODE -ne 0) { throw "falha ao subir o stack efêmero" }

    Write-Host "[e2e] aguardando backend em $BaseUrl/health ..." -ForegroundColor Cyan
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/health" -SkipCertificateCheck `
                    -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if (-not $ready) {
        docker @Compose logs --tail 60 backend | Out-Host
        throw "backend não ficou saudável a tempo"
    }
    Write-Host "[e2e] backend OK. Rodando Playwright..." -ForegroundColor Green

    Push-Location frontend
    try {
        $env:E2E_BASE_URL = $BaseUrl
        npm run test:e2e
        if ($LASTEXITCODE -ne 0) { throw "testes E2E falharam (exit $LASTEXITCODE)" }
    } finally { Pop-Location }

    Write-Host "[e2e] OK — todos os testes passaram." -ForegroundColor Green
}
catch {
    $failed = $true
    Write-Host "[e2e] FALHOU: $_" -ForegroundColor Red
}
finally {
    Invoke-Cleanup
}

if ($failed) { exit 1 }
