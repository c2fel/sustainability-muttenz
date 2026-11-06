# Betrieb auf dem Raspberry Pi

Der Collector braucht nur Python ≥ 3.11 (keine Zusatzpakete). Er läuft dauerhaft,
der Web-Root wird alle 15 Minuten neu erzeugt und lokal auf Port 8099 ausgeliefert.
Öffentlich erreichbar wird er über den bestehenden Cloudflare-Tunnel als
**`https://stats.jumut.ch/reports/charging/`**.

```
          ich-tanke-strom.ch (BFE)
                  │  HTTPS (ausgehend, < 2 Requests/min)
┌─────────────────▼──────────────────────── Raspberry Pi ─┐
│ collector ──► SQLite (data/ladestatistik.sqlite)         │
│ publish (15 min) ──► site/  (Web-Root)                   │
│     site/index.html                Übersicht             │
│     site/reports/charging/         Dashboard + data/*    │
│ serve 127.0.0.1:8099 ◄── cloudflared ◄───────────────────┼── stats.jumut.ch
│ (später API-Dienst :8100 ◄── cloudflared, Pfad /api/ ◄───┼── stats.jumut.ch/api/…)
│ EVCC :7070            ◄── cloudflared ◄───────────────────┼── charging.jumut.ch (Access)
│ git-publish.sh ──► GitHub, Branch "data" (optional)      │
└──────────────────────────────────────────────────────────┘
```

Welche Variante passt, hängt davon ab, wie Home Assistant installiert ist
(Einstellungen → System → Info → „Installationstyp“):

| Installationstyp | Variante |
|---|---|
| Home Assistant **OS** | C – lokales Add-on |
| Home Assistant **Container** / Supervised auf Raspberry Pi OS | A (systemd) oder B (Docker) |

## A – systemd (Raspberry Pi OS / Debian)

```bash
# Benutzer ohne Login; Home (SSH-Keys) getrennt vom Code-Verzeichnis
sudo useradd --system --create-home --home-dir /var/lib/ladestatistik --shell /usr/sbin/nologin ladestatistik
sudo mkdir /opt/ladestatistik && sudo chown ladestatistik: /opt/ladestatistik
sudo -u ladestatistik git clone https://github.com/c2fel/sustainability-muttenz.git /opt/ladestatistik
cd /opt/ladestatistik
sudo -u ladestatistik cp config.example.toml config.toml   # anpassen; Tarife: tarife.toml
sudo -u ladestatistik mkdir -p data site
sudo -u ladestatistik python3 -m ladestatistik -c config.toml collect --once   # Test
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ladestatistik-collector ladestatistik-web ladestatistik-publish.timer ladestatistik-tariffcheck.timer
python3 -m ladestatistik -c config.toml health
```

Bei privatem Repo: zum Klonen einen Deploy-Key verwenden (siehe unten).
Update: `cd /opt/ladestatistik && sudo -u ladestatistik git pull && sudo systemctl restart ladestatistik-collector ladestatistik-web`

Geänderte Preise in `tarife.toml` (z.B. per `git pull`) braucht keinen Neustart:
der nächste Publish-Lauf (alle 15 min) liest die Datei neu.

Der Preis-Check (`ladestatistik-tariffcheck.timer`, täglich 06:17) vergleicht die
Preisseiten der Betreiber mit `tarife.toml`; bei einer Abweichung schlägt der Dienst fehl
(`systemctl --failed`, `journalctl -u ladestatistik-tariffcheck`).

## B – Docker Compose

```bash
git clone https://github.com/c2fel/sustainability-muttenz.git && cd sustainability-muttenz
cp config.example.toml config.toml && mkdir -p data site
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

Der Webserver ist nur auf `127.0.0.1:8099` gebunden. Läuft `cloudflared` selbst in
einem Container, die Port-Bindung in `docker-compose.yml` anpassen oder beide
Container in dasselbe Docker-Netz hängen.

## C – Home Assistant OS (lokales Add-on)

1. Auf einem Rechner mit dem Repo: `sh deploy/homeassistant-addon/prepare.sh`
   (kopiert das Python-Paket in den Build-Ordner).
2. Den Ordner `deploy/homeassistant-addon/ladestatistik` nach `/addons/ladestatistik`
   auf Home Assistant kopieren (Add-on „Samba share“ oder „Advanced SSH & Web Terminal“).
3. Einstellungen → Add-ons → Add-on-Store → ⋮ → „Nach Updates suchen“ →
   unter „Lokale Add-ons“ *Ladestatistik Muttenz* installieren und starten.
4. Konfiguration, Tarife und Daten liegen in `/addon_configs/local_ladestatistik/`
   (`config.toml` und `tarife.toml` werden beim ersten Start aus dem Repo-Stand erzeugt;
   Preise danach direkt dort pflegen).
5. Lokal: `http://<ha-ip>:8099/reports/charging/`.

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

### Subdomain und Tunnel einrichten

`jumut.ch` ist bereits bei Cloudflare – eine Registrierung bei einem Registrar ist nicht
nötig. Beim Hinzufügen eines *Public Hostname* zum bestehenden Tunnel legt Cloudflare den
DNS-Eintrag `stats` (CNAME auf `<tunnel-id>.cfargotunnel.com`) automatisch an.

* **Im Dashboard verwalteter Tunnel** (Standard): Cloudflare Zero Trust → Networks →
  Tunnels → bestehenden Tunnel wählen → *Public Hostname* → *Add*:
  Subdomain `stats`, Domain `jumut.ch`, Path leer, Service `HTTP`, URL `localhost:8099`
  (Variante A/B) bzw. `local-ladestatistik:8099` oder `<ha-ip>:8099` (Variante C).
* **Home-Assistant-Add-on „Cloudflared“**: in den Add-on-Optionen unter
  `additional_hosts` ergänzen:
  ```yaml
  - hostname: stats.jumut.ch
    service: http://local-ladestatistik:8099
  ```
* **Lokal verwalteter Tunnel** (`config.yml`): siehe
  [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml).

Später für die API eine **zweite** Regel für denselben Hostnamen mit Path `^/api/` auf
den API-Dienst anlegen und **vor** die allgemeine Regel stellen (die erste passende Regel
gewinnt). Cloudflare entfernt den Pfad nicht: der API-Dienst erhält `/api/v1/…`. Bis dahin
beantwortet der Web-Root-Server `/api/…` mit 404.

Test nach der Einrichtung:
```bash
curl -I https://stats.jumut.ch/reports/charging/            # 200, Cache-Control: no-cache
curl -I https://stats.jumut.ch/reports/charging/data/daily.csv   # 200, max-age=300
curl -I https://stats.jumut.ch/reports/charging/data/       # 404 (keine Verzeichnisliste)
```

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
optional SSH-Fernwartung) nötig.

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
(als `ProxyCommand` in `~/.ssh/config`). So lassen sich Updates (`git pull`) einspielen,
ohne Ports am Router zu öffnen.

## Ressourcen

| | Standard-Konfiguration (Gemeinde Muttenz, ~50 Ladepunkte) |
|---|---|
| Netzwerk | ca. 200 MB/Tag Download – unabhängig vom Umfang, weil die BFE-Statusdateien immer die ganze Schweiz enthalten (v.a. OICP alle 2 min). Mit `oicp_interval_s = 300` und `ocpi_full_interval_s = 1800` ca. 80 MB/Tag |
| Speicher | wenige MB pro Monat (SQLite); mit `health` beobachten |
| CPU/RAM | vernachlässigbar (< 1 s pro Abruf, < 100 MB RAM) |
| SD-Karte | Intervall-Verlängerungen werden gesammelt alle 5 min geschrieben (`flush_interval_s`) |

Backup: `sqlite3 data/ladestatistik.sqlite ".backup data/backup.sqlite"` (konsistent
auch während der Collector läuft).
