#!/usr/bin/env bash
# Auto-Deploy: holt neue Commits des Deploy-Branches von GitHub, prüft sie und startet
# die Dienste neu. Läuft per systemd-Timer alle 2 Minuten (ladestatistik-autodeploy.timer).
#
# Ablauf: git fetch -> nichts Neues? Ende. -> auf neuen Stand wechseln -> Unit-Tests +
# Probe-Publish -> bei Fehler zurück auf den alten Stand (Commit wird gemerkt und nicht
# erneut versucht) -> sonst systemd-Units aktualisieren und Dienste neu starten.
#
# Einstellungen (Umgebung, z.B. in /etc/default/ladestatistik):
#   APP_DIR        Arbeitskopie des Repos            (Standard /opt/ladestatistik)
#   APP_USER       Besitzer der Arbeitskopie         (Standard ladestatistik)
#   DEPLOY_BRANCH  Branch, dem der Pi folgt          (Standard main)
#   DEPLOY_MODE    systemd | compose | none          (Standard systemd)
#   STATE_DIR      Merkt fehlgeschlagene Commits     (Standard /var/lib/ladestatistik)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ladestatistik}"
APP_USER="${APP_USER:-ladestatistik}"
BRANCH="${DEPLOY_BRANCH:-main}"
MODE="${DEPLOY_MODE:-systemd}"
STATE_DIR="${STATE_DIR:-/var/lib/ladestatistik}"
FAILED_FILE="$STATE_DIR/deploy-failed"
UNITS="ladestatistik-collector ladestatistik-web"

as_app() {
  if [ "$(id -un)" = "$APP_USER" ]; then "$@"; else runuser -u "$APP_USER" -- "$@"; fi
}
log() { echo "autodeploy: $*"; }

cd "$APP_DIR"
as_app git fetch --quiet origin "$BRANCH"
old="$(as_app git rev-parse HEAD)"
new="$(as_app git rev-parse "origin/$BRANCH")"
[ "$old" = "$new" ] && exit 0
if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$new" ]; then
  exit 0   # dieser Stand ist bereits einmal durchgefallen; auf den nächsten Push warten
fi
if [ -n "$(as_app git status --porcelain --untracked-files=no)" ]; then
  log "lokale Änderungen in $APP_DIR – Deploy abgebrochen (git status prüfen)"
  exit 1
fi

log "neuer Stand ${new:0:7} auf $BRANCH (bisher ${old:0:7})"
as_app git checkout --quiet -B "$BRANCH" "$new"

check() {
  as_app python3 -m unittest discover -s tests -q 2>&1 | tail -n 3 &&
  if [ -f config.toml ]; then as_app python3 -m ladestatistik -c config.toml publish --days 28; fi
}
if ! check; then
  log "Prüfung fehlgeschlagen – zurück auf ${old:0:7}"
  as_app git checkout --quiet -B "$BRANCH" "$old"
  mkdir -p "$STATE_DIR" && echo "$new" > "$FAILED_FILE"
  exit 1
fi
rm -f "$FAILED_FILE"

case "$MODE" in
  systemd)
    if ! as_app git diff --quiet "$old" "$new" -- deploy/systemd/; then
      log "systemd-Units aktualisiert"
      install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
      systemctl daemon-reload
    fi
    systemctl restart $UNITS
    systemctl start --no-block ladestatistik-publish.service
    ;;
  compose)
    docker compose -f deploy/docker/docker-compose.yml up -d --build --remove-orphans
    ;;
  none) ;;
  *) log "unbekannter DEPLOY_MODE '$MODE'"; exit 1 ;;
esac
log "deployt: ${new:0:7} – $(as_app git log -1 --format=%s "$new")"
