<#
.SYNOPSIS
  Cut a new release of the EdgeGate (PowerShell, Windows-friendly).

.DESCRIPTION
  Does everything, in order, so a release is one command:
    1. resolves the target version (bump patch/minor/major, or an explicit X.Y.Z)
    2. preflight checks (right branch, clean tree, tag unused, not behind remote)
    3. stamps CHANGELOG '[Não lançado]' -> '[X.Y.Z] - <date>', writes VERSION,
       commits "chore: release vX.Y.Z"
    4. creates the annotated tag vX.Y.Z
    5. pushes the branch AND the tag to origin  <-- the step that's easy to forget
    6. publishes the GitHub Release from the CHANGELOG section (via gh)

  The server's update-agent deploys the LATEST TAG, so forgetting to push the tag
  means the panel never sees the update. This always pushes both. It also always
  publishes the GitHub Release (from CHANGELOG.md '[Não lançado]', or --generate-notes
  as a fallback) so the Releases page never falls behind the tags again.

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
function Have-Gh { $null -ne (Get-Command gh -ErrorAction SilentlyContinue) }

# Pull the body of the "[Não lançado]" / "[Unreleased]" section out of a CHANGELOG.
function Get-UnreleasedNotes([string]$Path) {
  if (-not (Test-Path $Path)) { return $null }
  $lines = Get-Content -Path $Path
  $start = -1
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^##\s+\[(Não lançado|Unreleased)\]') { $start = $i; break }
  }
  if ($start -lt 0) { return $null }
  $body = New-Object System.Collections.Generic.List[string]
  for ($i = $start + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^##\s+\[') { break }
    $body.Add($lines[$i])
  }
  return (($body -join "`n").Trim())
}

# Stamp "[Não lançado]" as "[X.Y.Z] — <date>", reopen an empty Unreleased, fix compare links.
function Promote-Changelog([string]$Path, [string]$New, [string]$Date, [string]$Prev) {
  $raw = Get-Content -Raw $Path
  $sep = [char]0x2014   # em dash, matches the rest of the file
  $hdr = [regex]'(?m)^##\s+\[(?:Não lançado|Unreleased)\]\s*$'
  $raw = $hdr.Replace($raw, "## [Não lançado]`n`n## [$New] $sep $Date", 1)
  $lnk = [regex]'(?m)^\[(?:Não lançado|Unreleased)\]:\s*(?<base>\S+/compare/)v[0-9][0-9.]*\.\.\.HEAD\s*$'
  $m = $lnk.Match($raw)
  if ($m.Success) {
    $base = $m.Groups['base'].Value
    $raw = $lnk.Replace($raw, "[Não lançado]: ${base}v$New...HEAD`n[$New]: ${base}v$Prev...v$New", 1)
  }
  [System.IO.File]::WriteAllText($Path, $raw, (New-Object System.Text.UTF8Encoding($false)))
}

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

# ---- changelog notes (read BEFORE we rewrite the file) ----
$ChangelogFile = Join-Path $AppDir "CHANGELOG.md"
$ReleaseDate = (Get-Date -Format 'yyyy-MM-dd')
$Notes = Get-UnreleasedNotes $ChangelogFile
if ($Notes) { Info "CHANGELOG '[Não lançado]' has notes -> they become the $Tag release body" }
else { Warn "CHANGELOG has no '[Não lançado]' notes -> GitHub release will use --generate-notes" }

if ($DryRun) {
  Warn "[dry-run] would: write VERSION=$New + stamp CHANGELOG -> commit 'chore: release $Tag' -> tag $Tag -> push $Branch + $Tag"
  if (Have-Gh) { Warn "[dry-run] would: gh release create $Tag (from CHANGELOG)" }
  else { Warn "[dry-run] gh not found -> would print the manual 'gh release create' command" }
  exit 0
}

# ---- write VERSION (UTF-8, no BOM, trailing LF), commit, tag ----
Info "Writing VERSION -> $New (+ frontend/package.json, backend/app/__init__.py)"
[System.IO.File]::WriteAllText($VersionFile, "$New`n", (New-Object System.Text.UTF8Encoding($false)))
$PkgJson = Join-Path $AppDir "frontend/package.json"
$InitPy  = Join-Path $AppDir "backend/app/__init__.py"
if (Test-Path $PkgJson) { [System.IO.File]::WriteAllText($PkgJson, ((Get-Content -Raw $PkgJson) -replace '("version"\s*:\s*")\d+\.\d+\.\d+(")', "`${1}$New`${2}"), (New-Object System.Text.UTF8Encoding($false))) }
if (Test-Path $InitPy)  { [System.IO.File]::WriteAllText($InitPy,  ((Get-Content -Raw $InitPy)  -replace '(__version__\s*=\s*")\d+\.\d+\.\d+(")', "`${1}$New`${2}"), (New-Object System.Text.UTF8Encoding($false))) }
if (Test-Path $ChangelogFile) { Info "Stamping CHANGELOG '[Não lançado]' -> '[$New] $([char]0x2014) $ReleaseDate'"; Promote-Changelog $ChangelogFile $New $ReleaseDate $Current }
$AddFiles = @($VersionFile, $PkgJson, $InitPy, $ChangelogFile) | Where-Object { Test-Path $_ }
& git add -- $AddFiles
& git commit -m "chore: release $Tag" | Out-Null
Ok "Committed release $Tag"
& git tag -a $Tag -m $Tag
Ok "Tagged $Tag"

# ---- push branch + tag (both, always) ----
Info "Pushing $Branch + $Tag to $Remote ..."
& git push $Remote $Branch $Tag
if ($LASTEXITCODE -ne 0) { Die "git push failed" }
Ok "Pushed $Branch and tag $Tag to $Remote."

# ---- publish the GitHub Release (from the CHANGELOG) so it's never forgotten ----
if (Have-Gh) {
  Info "Publishing GitHub Release $Tag ..."
  $ghArgs = @('release', 'create', $Tag, '--title', $Tag, '--verify-tag')
  if ($Notes) {
    $tmp = New-TemporaryFile
    [System.IO.File]::WriteAllText($tmp.FullName, $Notes, (New-Object System.Text.UTF8Encoding($false)))
    $ghArgs += @('--notes-file', $tmp.FullName)
    & gh @ghArgs
    $rc = $LASTEXITCODE
    Remove-Item -Force $tmp.FullName
  } else {
    $ghArgs += '--generate-notes'
    & gh @ghArgs
    $rc = $LASTEXITCODE
  }
  if ($rc -ne 0) { Warn "gh release create failed (tag is pushed). Retry: gh release create $Tag --title $Tag --verify-tag --notes-file <notes>" }
  else { Ok "GitHub Release $Tag published." }
} else {
  Warn "gh CLI not found - GitHub Release NOT created. Run: gh release create $Tag --title $Tag --verify-tag --notes-file <notes-from-CHANGELOG>"
}
Ok "Release $Tag is live on $Remote."

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  - Panel -> 'check for updates' (should offer $New), then trigger the update."
Write-Host "  - update.sh deploys tag ${Tag}: builds before switching, health-gates, auto-rolls-back."
