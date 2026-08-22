<#
.SYNOPSIS
  Cut a new release of the EdgeGate (PowerShell, Windows-friendly).

.DESCRIPTION
  Does everything, in order, so a release is one command:
    1. resolves the target version (bump patch/minor/major, or an explicit X.Y.Z)
    2. preflight checks (right branch, clean tree, tag unused, not behind remote)
    3. writes VERSION, commits "chore: release vX.Y.Z"
    4. creates the annotated tag vX.Y.Z
    5. pushes the branch AND the tag to origin  <-- the step that's easy to forget

  The server's update-agent deploys the LATEST TAG, so forgetting to push the tag
  means the panel never sees the update. This always pushes both.

.EXAMPLE
  .\scripts\release.ps1                # bump patch  (1.1.8 -> 1.1.9)
  .\scripts\release.ps1 minor          # 1.1.8 -> 1.2.0
  .\scripts\release.ps1 1.3.0          # explicit version ('v' prefix ok too)
  .\scripts\release.ps1 patch -DryRun  # show what it would do, change nothing
#>
[CmdletBinding()]
param(
  [string]$Bump = "patch",
  [string]$Remote = "origin",
  [string]$Branch = "main",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "==> $m" -ForegroundColor Green }
function Warn($m) { Write-Host "==> $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "error: $m" -ForegroundColor Red; exit 1 }
function Git-Ok([string[]]$GitArgs) { & git @GitArgs *> $null; return ($LASTEXITCODE -eq 0) }

# ---- locate repo + VERSION ----
$AppDir = Split-Path -Parent $PSScriptRoot           # repo root
$VersionFile = Join-Path $AppDir "VERSION"
if (-not (Test-Path $VersionFile)) { Die "VERSION file not found at $VersionFile" }
Set-Location $AppDir
if (-not (Git-Ok @("rev-parse", "--is-inside-work-tree"))) { Die "not inside a git repository" }

$Current = (Get-Content -Raw $VersionFile).Trim()
if ($Current -notmatch '^\d+\.\d+\.\d+$') { Die "current VERSION '$Current' is not X.Y.Z" }
Info "Current version: $Current"

# ---- resolve target version ----
if ($Bump -in @('major', 'minor', 'patch')) {
  $parts = $Current.Split('.')
  [int]$ma = $parts[0]; [int]$mi = $parts[1]; [int]$pa = $parts[2]
  switch ($Bump) {
    'major' { $ma++; $mi = 0; $pa = 0 }
    'minor' { $mi++; $pa = 0 }
    'patch' { $pa++ }
  }
  $New = "$ma.$mi.$pa"
}
else {
  $New = $Bump.TrimStart('v')
  if ($New -notmatch '^\d+\.\d+\.\d+$') { Die "invalid argument '$Bump' (use: patch | minor | major | X.Y.Z)" }
}
$Tag = "v$New"
Info "Target version: $New  (tag $Tag)"
if ($New -eq $Current) { Die "target version equals current ($Current); nothing to release" }

# ---- preflight ----
$curBranch = (& git rev-parse --abbrev-ref HEAD).Trim()
if ($curBranch -ne $Branch) { Die "on branch '$curBranch', expected '$Branch' (use -Branch to override)" }

& git diff --quiet; $dirty1 = $LASTEXITCODE
& git diff --cached --quiet; $dirty2 = $LASTEXITCODE
if ($dirty1 -ne 0 -or $dirty2 -ne 0) { & git status --short; Die "working tree not clean - commit or stash first" }

if (Git-Ok @("rev-parse", "-q", "--verify", "refs/tags/$Tag")) { Die "tag $Tag already exists locally" }
if (Git-Ok @("ls-remote", "--exit-code", "--tags", $Remote, $Tag)) { Die "tag $Tag already exists on $Remote" }

Info "Fetching $Remote ..."
& git fetch --quiet $Remote $Branch --tags
if (Git-Ok @("rev-parse", "-q", "--verify", "$Remote/$Branch")) {
  if (-not (Git-Ok @("merge-base", "--is-ancestor", "$Remote/$Branch", $Branch))) {
    Die "local $Branch is behind/diverged from $Remote/$Branch - run: git pull --ff-only $Remote $Branch"
  }
}
Ok "Preflight OK"

if ($DryRun) {
  Warn "[dry-run] would: write VERSION=$New -> commit 'chore: release $Tag' -> tag $Tag -> push $Branch + $Tag"
  exit 0
}

# ---- write VERSION (UTF-8, no BOM, trailing LF), commit, tag ----
Info "Writing VERSION -> $New"
[System.IO.File]::WriteAllText($VersionFile, "$New`n", (New-Object System.Text.UTF8Encoding($false)))
& git add -- $VersionFile
& git commit -m "chore: release $Tag" | Out-Null
Ok "Committed release $Tag"
& git tag -a $Tag -m $Tag
Ok "Tagged $Tag"

# ---- push branch + tag (both, always) ----
Info "Pushing $Branch + $Tag to $Remote ..."
& git push $Remote $Branch $Tag
if ($LASTEXITCODE -ne 0) { Die "git push failed" }
Ok "Release $Tag is live on $Remote."

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  - Panel -> 'check for updates' (should offer $New), then trigger the update."
Write-Host "  - update.sh deploys tag ${Tag}: builds before switching, health-gates, auto-rolls-back."
