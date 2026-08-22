#!/usr/bin/env bash
#
# release.sh - Cut a new release of the EdgeGate.
#
# Does everything, in order, so a release is one command and you just watch the logs:
#   1. resolves the target version (bump patch/minor/major, or an explicit X.Y.Z)
#   2. preflight checks (on the right branch, clean tree, tag not already used,
#      local branch not behind the remote)
#   3. writes VERSION, commits "chore: release vX.Y.Z"
#   4. creates the annotated git tag vX.Y.Z
#   5. pushes the branch AND the tag to origin  <-- the step that's easy to forget
#
# The running server's update-agent deploys the LATEST TAG, so forgetting to push
# the tag means the panel never sees the update. This script always pushes both.
#
# Usage:
#   ./scripts/release.sh                # bump patch  (1.1.7 -> 1.1.8)
#   ./scripts/release.sh patch|minor|major
#   ./scripts/release.sh 1.2.0          # explicit version
#   ./scripts/release.sh v1.2.0         # 'v' prefix is fine
#
# Options via env:
#   RELEASE_REMOTE (default: origin)
#   RELEASE_BRANCH (default: main)
#   DRY_RUN=1       # do everything except commit/tag/push (prints what it would do)
#
set -euo pipefail

# ---- locate repo + VERSION (works no matter where it's called from) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"          # repo root
VERSION_FILE="$APP_DIR/VERSION"
REMOTE="${RELEASE_REMOTE:-origin}"
BRANCH="${RELEASE_BRANCH:-main}"
DRY_RUN="${DRY_RUN:-0}"

# ---- pretty logging ----
if [ -t 1 ]; then
  C='\033[0;36m'; G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; N='\033[0m'
else
  C=''; G=''; Y=''; R=''; N=''
fi
log()  { printf "${C}==>${N} %s\n" "$*"; }
ok()   { printf "${G}==>${N} %s\n" "$*"; }
warn() { printf "${Y}==>${N} %s\n" "$*"; }
die()  { printf "${R}error:${N} %s\n" "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = "1" ]; then printf "${Y}[dry-run]${N} %s\n" "$*"; else eval "$@"; fi; }

[ -f "$VERSION_FILE" ] || die "VERSION file not found at $VERSION_FILE"
cd "$APP_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"

CURRENT="$(tr -d ' \t\r\n' < "$VERSION_FILE")"
echo "$CURRENT" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "current VERSION '$CURRENT' is not X.Y.Z"
log "Current version: $CURRENT"

# ---- resolve target version ----
BUMP="${1:-patch}"
case "$BUMP" in
  major|minor|patch)
    IFS='.' read -r MA MI PA <<EOF2
$CURRENT
EOF2
    case "$BUMP" in
      major) MA=$((MA + 1)); MI=0; PA=0 ;;
      minor) MI=$((MI + 1)); PA=0 ;;
      patch) PA=$((PA + 1)) ;;
    esac
    NEW="$MA.$MI.$PA"
    ;;
  *)
    NEW="${BUMP#v}"
    echo "$NEW" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
      || die "invalid argument '$BUMP' (use: patch | minor | major | X.Y.Z)"
    ;;
esac
TAG="v$NEW"
log "Target version: ${G}$NEW${N}  (tag $TAG)"
[ "$NEW" != "$CURRENT" ] || die "target version equals current ($CURRENT); nothing to release"

# ---- preflight ----
CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$CUR_BRANCH" = "$BRANCH" ] || die "on branch '$CUR_BRANCH', expected '$BRANCH' (override with RELEASE_BRANCH)"

if ! git diff --quiet || ! git diff --cached --quiet; then
  git status --short
  die "working tree not clean — commit or stash your changes first"
fi

git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1 && die "tag $TAG already exists locally"
if git ls-remote --exit-code --tags "$REMOTE" "$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists on $REMOTE"
fi

log "Fetching $REMOTE ..."
git fetch --quiet "$REMOTE" "$BRANCH" --tags
if git rev-parse -q --verify "$REMOTE/$BRANCH" >/dev/null 2>&1; then
  if ! git merge-base --is-ancestor "$REMOTE/$BRANCH" "$BRANCH"; then
    die "local $BRANCH is behind/diverged from $REMOTE/$BRANCH — run: git pull --ff-only $REMOTE $BRANCH"
  fi
fi
ok "Preflight OK"

# ---- write VERSION, commit, tag ----
log "Writing VERSION -> $NEW"
if [ "$DRY_RUN" != "1" ]; then printf '%s\n' "$NEW" > "$VERSION_FILE"; fi
run "git add '$VERSION_FILE'"
run "git commit -m 'chore: release $TAG'"
ok "Committed release $TAG"
run "git tag -a '$TAG' -m '$TAG'"
ok "Tagged $TAG"

# ---- push branch + tag (both, always) ----
log "Pushing $BRANCH + $TAG to $REMOTE ..."
run "git push '$REMOTE' '$BRANCH' '$TAG'"
ok "Pushed $BRANCH and tag $TAG to $REMOTE"

echo
ok "Release $TAG is live on $REMOTE."
cat <<EOF3

Next steps:
  - Open the panel -> "check for updates": it should now offer $NEW.
  - Trigger the update; the update-agent deploys tag $TAG via update.sh
    (builds before switching, health-gates, auto-rolls-back on failure).
EOF3
