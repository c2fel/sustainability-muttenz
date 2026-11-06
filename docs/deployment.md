# Betrieb auf dem Raspberry Pi – Referenz

**Schritt-für-Schritt-Anleitung: [inbetriebnahme.md](inbetriebnahme.md)** (Installation,
Auto-Deploy, Tunnel, Subdomain). Dieses Dokument beschreibt Aufbau und Einstellungen.

Der Collector braucht nur Python ≥ 3.11 (keine Zusatzpakete). Er läuft dauerhaft,
der Web-Root wird alle 15 Minuten neu erzeugt und lokal auf Port 8099 ausgeliefert.
Öffentlich erreichbar wird er über den bestehenden Cloudflare-Tunnel als
**`https://stats.jumut.ch/reports/charging/`**.

```
   GitHub (main) ──── git fetch alle 2 min ─────────────┐
          ich-tanke-strom.ch (BFE)                      │
                  │  HTTPS (ausgehend, < 2 Requests/min) │
┌─────────────────▼──────────────────────── Raspberry Pi ▼┐
│ autodeploy: Tests → Probe-Publish → Neustart/Rollback    │
│ collector ──► SQLite (data/ladestatistik.sqlite)         │
│ publish (15 min) ──► site/  (Web-Root)                   │
│     site/index.html, version.json  Übersicht, Version    │
│     site/reports/charging/         Dashboard + data/*    │
│ tariff-check (täglich) ──► Betreiber-Preisseiten         │
│ serve 127.0.0.1:8099 ◄── cloudflared ◄───────────────────┼── stats.jumut.ch
│ (später API-Dienst :8100 ◄── cloudflared, Pfad /api/ ◄───┼── stats.jumut.ch/api/…)
│ EVCC :7070            ◄── cloudflared ◄───────────────────┼── charging.jumut.ch (Access)
│ git-publish.sh ──► GitHub, Branch "data" (optional)      │
└──────────────────────────────────────────────────────────┘
```

## Dienste je Installationsart

| Aufgabe | A: systemd | B: Docker Compose | C: HA-OS-Add-on |
|---|---|---|---|
| Collector | `ladestatistik-collector.service` | Dienst `collector` | Supervisor |
| Webserver :8099 | `ladestatistik-web.service` | Dienst `web` | Supervisor |
| Dashboard alle 15 min | `ladestatistik-publish.timer` | Dienst `publisher` | Supervisor |
| Preis-Check täglich | `ladestatistik-tariffcheck.timer` | Dienst `pricewatch` | Supervisor |
| Auto-Deploy alle 2 min | `ladestatistik-autodeploy.timer` (`deploy/autodeploy.sh`) | dito, `DEPLOY_MODE=compose` | Supervisor (`poll_seconds`) |
| Einstellungen Auto-Deploy | `/etc/default/ladestatistik` | dito | Add-on-Optionen `branch`, `poll_seconds` |
| Protokoll | `journalctl -u ladestatistik-*` | `docker compose logs` | Add-on-Protokoll |

Geänderte Preise in `tarife.toml` brauchen keinen Neustart: der nächste Publish-Lauf liest
die Datei neu. Der Preis-Check schlägt bei einer Abweichung fehl (A: `systemctl --failed`,
`journalctl -u ladestatistik-tariffcheck`).

## Veröffentlichung unter stats.jumut.ch

### URL-Struktur

| URL | Inhalt | Dienst |
|---|---|---|
| `https://stats.jumut.ch/` | Übersicht der Reports | Web-Root (`serve`, Port 8099) |
| `https://stats.jumut.ch/reports/charging/` | Dashboard Ladestatistik Muttenz | dito |
| `https://stats.jumut.ch/reports/charging/data/summary.json` | Kennzahlen (JSON) | dito |
| `https://stats.jumut.ch/reports/charging/data/daily.csv` | Tageswerte je Ladepunkt | dito |
| `https://stats.jumut.ch/reports/charging/data/evses.csv` | Ladepunkte mit Kennzahlen und Tarif | dito |
| `https://stats.jumut.ch/reports/<weitere>/` | künftige Reports | dito |
| `https://stats.jumut.ch/api/v1/…` | künftige API | eigener Dienst, eigene Tunnel-Regel |

* Kanonische Adresse mit Schrägstrich am Ende: `/reports/charging/`. Ohne Schrägstrich
  leitet der Server weiter (301), damit die relativen Links auf `data/…` stimmen.
* Der Report-Pfad ist konfigurierbar (`[publish] report_path`); Dashboard und Downloads
  verwenden nur relative Links.
* Die API später mit Versionsnummer anlegen (`/api/v1/…`), damit Änderungen möglich
  bleiben, ohne bestehende Abnehmer zu brechen.

### Tunnel und Subdomain

Einrichtung: [inbetriebnahme.md, Schritte 3 und 4](inbetriebnahme.md#3-tunnel-statsjumutch-hinzufügen).
Vorlage für lokal verwaltete Tunnel: [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml).

Später für die API eine **zweite** Regel für denselben Hostnamen mit Path `^/api/` auf
den API-Dienst anlegen und **vor** die allgemeine Regel stellen (die erste passende Regel
gewinnt). Cloudflare entfernt den Pfad nicht: der API-Dienst erhält `/api/v1/…`. Bis dahin
beantwortet der Web-Root-Server `/api/…` mit 404.

### Zugriffsschutz (Cloudflare Access)

`charging.jumut.ch` (EVCC) ist durch Cloudflare Access geschützt und bleibt davon getrennt.
Für `stats.jumut.ch` lassen sich Access-Applikationen **pro Pfad** anlegen, z.B.:

* `stats.jumut.ch/reports/charging` → öffentlich (keine Access-App) oder Team-Login,
* `stats.jumut.ch/api` → später Service-Token für Maschinen-Zugriffe.

Vor einer öffentlichen Freigabe die BFE-Nutzungsbedingungen klären
(siehe [datenquellen.md](datenquellen.md#nutzungsbedingungen)). Bis dahin setzt der
Web-Root `robots.txt: Disallow` und `noindex` (`[publish] allow_indexing = false`).

### Webserver

`python -m ladestatistik serve` liefert nur statische Dateien aus `site/` aus: keine
Verzeichnislisten, nur GET/HEAD, `Cache-Control` (HTML nie, JSON/CSV 5 min – Cloudflare
würde CSV sonst bis zu 2 h zwischenspeichern), `nosniff`, Content-Security-Policy.
Kein Schreibzugriff, kein Datenbankzugriff.

## Daten nach GitHub pushen

Ein `git push` vom Pi zu GitHub ist eine **ausgehende** Verbindung und braucht keinen
Cloudflare-Tunnel. Der Tunnel ist nur für **eingehende** Zugriffe (stats.jumut.ch, EVCC,
optional SSH-Fernwartung) nötig. Zum *Abholen* des Codes (Auto-Deploy) braucht der Pi keinen
Schlüssel, weil das Repo öffentlich ist; nur das optionale Zurückschreiben der Daten in den
Branch `data` benötigt einen Deploy-Key mit Schreibrecht.

Einrichtung (einmalig):

```bash
# Schlüssel liegt im Home des Dienstbenutzers – nie im Repo-Verzeichnis
sudo -u ladestatistik mkdir -p -m 700 /var/lib/ladestatistik/.ssh
sudo -u ladestatistik ssh-keygen -t ed25519 -N "" -f /var/lib/ladestatistik/.ssh/github_ladestatistik
cat /var/lib/ladestatistik/.ssh/github_ladestatistik.pub
#   → GitHub: Repo → Settings → Deploy keys → Add deploy key, "Allow write access"
cat <<'EOF' | sudo -u ladestatistik tee -a /var/lib/ladestatistik/.ssh/config
Host github-ladestatistik
  HostName github.com
  User git
  IdentityFile ~/.ssh/github_ladestatistik
  IdentitiesOnly yes
EOF
```

Dann in `deploy/systemd/ladestatistik-publish.service` die Zeile `ExecStartPost=` aktivieren.
`deploy/git-publish.sh` committet höchstens einmal pro Stunde den Web-Root (gleiche Pfade
wie auf stats.jumut.ch, also `docs/reports/charging/…`) in den separaten Branch **`data`**
(nicht die SQLite-Datenbank, nicht `main`). Der Deploy-Key gilt nur für dieses eine Repo.

Optional GitHub Pages: Settings → Pages → Branch `data`, Ordner `/docs`
(bei privaten Repos nur mit kostenpflichtigem GitHub-Plan).

### Fernwartung per SSH über den Tunnel (optional)

Public Hostname `ssh-pi.jumut.ch` → Service `SSH`, URL `localhost:22`, mit
Access-Policy. Zugriff vom Laptop: `cloudflared access ssh --hostname ssh-pi.jumut.ch`
(als `ProxyCommand` in `~/.ssh/config`). Für Code-Updates nicht nötig (Auto-Deploy),
aber praktisch für Wartung, ohne Ports am Router zu öffnen.

## Ressourcen

| | Standard-Konfiguration (Gemeinde Muttenz, ~50 Ladepunkte) |
|---|---|
| Netzwerk | ca. 200 MB/Tag Download – unabhängig vom Umfang, weil die BFE-Statusdateien immer die ganze Schweiz enthalten (v.a. OICP alle 2 min). Mit `oicp_interval_s = 300` und `ocpi_full_interval_s = 1800` ca. 80 MB/Tag |
| Speicher | wenige MB pro Monat (SQLite); mit `health` beobachten |
| CPU/RAM | vernachlässigbar (< 1 s pro Abruf, < 100 MB RAM) |
| SD-Karte | Intervall-Verlängerungen werden gesammelt alle 5 min geschrieben (`flush_interval_s`) |

Backup: `sqlite3 data/ladestatistik.sqlite ".backup data/backup.sqlite"` (konsistent
auch während der Collector läuft).
