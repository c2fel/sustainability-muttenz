#!/usr/bin/env bash
# Pusht den erzeugten Web-Root (Übersicht, reports/charging/ mit Dashboard + CSV/JSON,
# ohne Rohdatenbank) in den Branch "data", Ordner docs/.
#
# Voraussetzungen (einmalig, siehe docs/deployment.md):
#   - Deploy-Key mit Schreibrecht für dieses Repo, in ~/.ssh/config als Host "github-ladestatistik"
#   - Arbeitskopie für den Branch "data" unter $WORKTREE (wird automatisch angelegt)
#
# Aufruf: deploy/git-publish.sh <site-verzeichnis>
# Commit nur, wenn sich Daten geändert haben; höchstens ein Commit pro Stunde,
# damit die Git-Historie nicht explodiert.
set -euo pipefail

SITE_DIR="${1:-/opt/ladestatistik/site}"
WORKTREE="${WORKTREE:-/var/lib/ladestatistik/publish-repo}"
REMOTE="${REMOTE:-git@github-ladestatistik:c2fel/sustainability-muttenz.git}"
BRANCH="${BRANCH:-data}"
MIN_INTERVAL_S="${MIN_INTERVAL_S:-3600}"

if [ ! -d "$WORKTREE/.git" ]; then
  git clone --depth 1 --branch "$BRANCH" "$REMOTE" "$WORKTREE" 2>/dev/null || {
    git init -q "$WORKTREE"
    git -C "$WORKTREE" remote add origin "$REMOTE"
    git -C "$WORKTREE" checkout -q -b "$BRANCH"
  }
fi
cd "$WORKTREE"

last=$(git log -1 --format=%ct 2>/dev/null || echo 0)
if [ $(( $(date +%s) - last )) -lt "$MIN_INTERVAL_S" ]; then
  exit 0
fi

# Web-Root 1:1 spiegeln (gleiche Pfade wie auf stats.jumut.ch)
git rm -rq --ignore-unmatch docs
mkdir -p docs
cp -R "$SITE_DIR"/. docs/
find docs -name '*.tmp' -delete

git add -A docs
if git diff --cached --quiet; then
  exit 0
fi
git -c user.name="ladestatistik-pi" -c user.email="ladestatistik@users.noreply.github.com" \
  commit -q -m "Daten $(date -u +%Y-%m-%dT%H:%MZ)"
for delay in 2 4 8 16; do
  git push -q -u origin "$BRANCH" && exit 0
  sleep "$delay"
done
echo "git push fehlgeschlagen" >&2
exit 1
