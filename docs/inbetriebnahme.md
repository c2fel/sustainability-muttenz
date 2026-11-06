# Inbetriebnahme auf dem Raspberry Pi

Am Ende dieser Anleitung gilt:

* `https://stats.jumut.ch/reports/charging/` zeigt das Dashboard (über den bestehenden
  Cloudflare-Tunnel, neben `charging.jumut.ch`),
* jeder Push auf den Branch `main` wird auf dem Pi innerhalb von ~2 Minuten automatisch
  geprüft (Unit-Tests + Probe-Dashboard) und ausgerollt – bei einem Fehler bleibt der alte
  Stand aktiv,
* die Preisseiten der Betreiber werden täglich mit `tarife.toml` verglichen.

Referenz (Architektur, URL-Struktur, Webserver, Ressourcen): [deployment.md](deployment.md)

---

## 0. Vorbereitung

1. **Code nach `main` bringen.** Der Pi folgt dem Branch `main`. Der aktuelle Stand liegt auf
   `claude/muttenz-charging-analysis-44bv84` → auf GitHub einen Pull Request nach `main`
   erstellen und mergen. (Alternativ vorübergehend den Feature-Branch einstellen, siehe
   `DEPLOY_BRANCH` bzw. Add-on-Option `branch`.)
2. **Das Repo ist öffentlich.** Der Pi holt den Code ohne Schlüssel. `config.toml` (lokale
   Einstellungen) liegt nur auf dem Pi und wird nie überschrieben.

## 1. Installationsart und Tunnel-Art ermitteln

**Home Assistant:** Einstellungen → System → Info → „Installationstyp“

| Installationstyp | Variante in Schritt 2 |
|---|---|
| Home Assistant OS | **C** – lokales Add-on |
| Home Assistant Container oder Supervised (auf Raspberry Pi OS) | **A** – systemd (empfohlen) oder **B** – Docker Compose |

**Cloudflare-Tunnel:** `stats.jumut.ch` wird genau so eingerichtet wie das bestehende
`charging.jumut.ch`. Herausfinden, wie dieser Tunnel läuft:

| Prüfen | Ergebnis | Tunnel-Art |
|---|---|---|
| HA: Einstellungen → Add-ons → „Cloudflared“ vorhanden? | Option `tunnel_token` gesetzt | im Dashboard verwaltet |
| | kein Token, aber `external_hostname` / `additional_hosts` | Add-on, lokal verwaltet |
| Pi OS: `systemctl cat cloudflared` | `ExecStart=… --token …` | im Dashboard verwaltet |
| | `ExecStart=… --config /etc/cloudflared/config.yml …` | lokal verwaltet (`config.yml`) |
| Docker: `docker ps \| grep cloudflared` | Container mit `--token` | im Dashboard verwaltet |
| Cloudflare: Zero Trust → Networks → Tunnels | Tunnel mit Knopf „Configure“ | im Dashboard verwaltet |

## 2. Installation (inkl. Auto-Deploy)

### A – Raspberry Pi OS mit systemd

```bash
python3 --version          # ≥ 3.11 (Raspberry Pi OS Bookworm: 3.11)
sudo apt install -y git

# Dienstbenutzer ohne Login, Code unter /opt/ladestatistik
sudo useradd --system --create-home --home-dir /var/lib/ladestatistik \
     --shell /usr/sbin/nologin ladestatistik
sudo mkdir /opt/ladestatistik && sudo chown ladestatistik: /opt/ladestatistik
sudo -u ladestatistik git clone --branch main \
     https://github.com/c2fel/sustainability-muttenz.git /opt/ladestatistik
cd /opt/ladestatistik

# Konfiguration + erster Test
sudo -u ladestatistik cp config.example.toml config.toml
sudo -u ladestatistik mkdir -p data site
sudo -u ladestatistik python3 -m unittest discover -s tests -q
sudo -u ladestatistik python3 -m ladestatistik -c config.toml collect --once
sudo -u ladestatistik python3 -m ladestatistik -c config.toml publish

# Dienste, Timer und Auto-Deploy
sudo install -m 0644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo install -m 0644 deploy/systemd/ladestatistik.default /etc/default/ladestatistik
sudo systemctl daemon-reload
sudo systemctl enable --now ladestatistik-collector ladestatistik-web \
     ladestatistik-publish.timer ladestatistik-tariffcheck.timer ladestatistik-autodeploy.timer

# Kontrolle
systemctl --no-pager status ladestatistik-collector ladestatistik-web
curl -sI http://127.0.0.1:8099/reports/charging/ | head -1      # HTTP/1.0 200 OK
sudo -u ladestatistik python3 -m ladestatistik -c config.toml health
```

Einstellungen für das Auto-Deploy stehen in `/etc/default/ladestatistik` (Branch, Modus).
Der Webserver lauscht nur auf `127.0.0.1:8099`. Läuft `cloudflared` in einem Docker-Container
ohne Host-Netzwerk, in `deploy/systemd/ladestatistik-web.service` `--host 0.0.0.0` setzen
(Port 8099 dann nicht im Router freigeben).

### B – Docker Compose

```bash
sudo mkdir /opt/ladestatistik && sudo chown "$USER": /opt/ladestatistik
git clone --branch main https://github.com/c2fel/sustainability-muttenz.git /opt/ladestatistik
cd /opt/ladestatistik
cp config.example.toml config.toml && mkdir -p data site
docker compose -f deploy/docker/docker-compose.yml up -d --build

# Auto-Deploy auf dem Host (Tests laufen mit dem Python des Hosts, ≥ 3.11)
sudo install -m 0644 deploy/systemd/ladestatistik-autodeploy.* /etc/systemd/system/
sudo install -m 0644 deploy/systemd/ladestatistik.default /etc/default/ladestatistik
sudo sed -i "s/^APP_USER=.*/APP_USER=$USER/; s/^DEPLOY_MODE=.*/DEPLOY_MODE=compose/" \
     /etc/default/ladestatistik
sudo systemctl daemon-reload && sudo systemctl enable --now ladestatistik-autodeploy.timer
```

### C – Home Assistant OS (lokales Add-on)

Das Add-on enthält nur einen kleinen Supervisor: Er holt den Code beim Start von GitHub,
startet die Dienste und rollt neue Commits selbst aus (Auto-Deploy eingebaut).

1. Add-on **„Advanced SSH & Web Terminal“** (oder „Terminal & SSH“) öffnen und die vier
   Add-on-Dateien holen:
   ```bash
   mkdir -p /addons/ladestatistik && cd /addons/ladestatistik
   for f in config.yaml build.yaml Dockerfile supervisor.py; do
     wget -q "https://raw.githubusercontent.com/c2fel/sustainability-muttenz/main/deploy/homeassistant-addon/ladestatistik/$f"
   done
   ls    # config.yaml  build.yaml  Dockerfile  supervisor.py
   ```
2. Einstellungen → Add-ons → Add-on-Store → ⋮ → **„Nach Updates suchen“** → unter
   „Lokale Add-ons“ **Ladestatistik Muttenz** → *Installieren* (baut das Image, einige Minuten).
3. Reiter *Konfiguration*: `branch: main` (bzw. vorübergehend den Feature-Branch),
   `poll_seconds: 120`. Reiter *Info*: „Beim Booten starten“ an → *Starten*.
4. Reiter *Protokoll*: `Dienste gestartet (Stand abc1234)`.
5. Lokal testen: `http://<ha-ip>:8099/reports/charging/`.

Einstellungen und Datenbank: `/addon_configs/local_ladestatistik/` (`config.toml`, `data/`,
`site/`). Die Tarife kommen aus dem Repo: Änderungen an `tarife.toml` auf GitHub sind nach
dem nächsten Auto-Deploy aktiv.

## 3. Tunnel: `stats.jumut.ch` hinzufügen

Es braucht **keinen neuen Tunnel**. Der bestehende Tunnel bekommt einen zweiten Hostnamen.
Die Ziel-Adresse (Service) hängt von der Installationsart ab:

| Installation | Service-URL |
|---|---|
| A (systemd), cloudflared auf demselben Pi | `http://localhost:8099` |
| B (Docker), cloudflared auf dem Host | `http://localhost:8099` |
| C (HA-Add-on), Cloudflared-Add-on | `http://local-ladestatistik:8099`, alternativ `http://<ha-ip>:8099` |

**Im Dashboard verwalteter Tunnel** (häufigster Fall): Cloudflare → Zero Trust → Networks →
Tunnels → Tunnel wählen → *Configure* → Reiter **Public Hostname** (neuere Oberfläche:
„Published application routes“) → *Add*:

* Subdomain `stats`, Domain `jumut.ch`, Path leer
* Type `HTTP`, URL gemäss Tabelle oben (ohne `http://` im URL-Feld)
* *Save* – der DNS-Eintrag wird automatisch angelegt.

**Home-Assistant-Add-on „Cloudflared“ ohne Token** (lokal verwaltet): in den Add-on-Optionen
ergänzen und das Cloudflared-Add-on neu starten:
```yaml
additional_hosts:
  - hostname: stats.jumut.ch
    service: http://local-ladestatistik:8099
```
Das Add-on legt den DNS-Eintrag beim Start an (im Add-on-Protokoll kontrollieren).
Mit gesetztem `tunnel_token` werden `additional_hosts` ignoriert → wie oben im Dashboard
eintragen.

**Lokal verwalteter Tunnel** (`/etc/cloudflared/config.yml`):
```bash
sudo nano /etc/cloudflared/config.yml     # Regel für stats.jumut.ch VOR der 404-Regel,
                                          # Vorlage: deploy/cloudflared/config.example.yml
sudo cloudflared tunnel ingress validate
sudo cloudflared tunnel ingress rule https://stats.jumut.ch/reports/charging/
sudo cloudflared tunnel route dns <TUNNEL-NAME> stats.jumut.ch   # DNS-Eintrag anlegen
sudo systemctl restart cloudflared
```

**Noch kein Tunnel / eigener Tunnel gewünscht:** Zero Trust → Networks → Tunnels →
*Create a tunnel* → *Cloudflared* → Name (z.B. `jumut-pi`) → angezeigten Befehl
`sudo cloudflared service install <TOKEN>` auf dem Pi ausführen → Public Hostname wie oben.

## 4. Subdomain `stats.jumut.ch` in Cloudflare konfigurieren

`jumut.ch` ist bereits bei Cloudflare; eine Registrierung beim Registrar ist nicht nötig.

1. **DNS** (Cloudflare → jumut.ch → DNS → Records): Eintrag `stats`, Typ `CNAME`,
   Ziel `<tunnel-id>.cfargotunnel.com`, **Proxied** (orange Wolke). Wurde in Schritt 3
   automatisch angelegt. Fehlermeldung „record already exists“ → alten `stats`-Eintrag
   zuerst löschen.
2. **TLS:** Das Universal-SSL-Zertifikat deckt `*.jumut.ch` ab – kein eigenes Zertifikat
   nötig. SSL/TLS → Edge Certificates → „Always Use HTTPS“ einschalten. Der
   Verschlüsselungsmodus spielt für Tunnel-Ziele keine Rolle.
3. **Zugriff** (Zero Trust → Access → Applications) – bewusst entscheiden:
   * *Nur intern:* Applikation „Self-hosted“, Domain `stats.jumut.ch`, Policy wie bei
     `charging.jumut.ch`.
   * *Öffentlich:* keine Applikation für `stats.jumut.ch`. **Prüfen, dass keine
     Wildcard-Applikation `*.jumut.ch` existiert** – sie würde auch `stats` schützen.
   * *Später gemischt:* Applikation nur für den Pfad `stats.jumut.ch/api` (Service-Token).
   Vor einer öffentlichen Freigabe die BFE-Nutzungsbedingungen klären
   ([datenquellen.md](datenquellen.md#nutzungsbedingungen)). Bis dahin sperrt der Web-Root
   Suchmaschinen (`robots.txt`, `noindex`; `[publish] allow_indexing = false`).
4. **Caching:** nichts einrichten. Der Server schickt passende `Cache-Control`-Header
   (HTML nie, CSV/JSON 5 min).

Test (von einem beliebigen Rechner):
```bash
curl -sI https://stats.jumut.ch/reports/charging/ | head -1   # 200 (bzw. 302 zu Access, falls geschützt)
curl -s  https://stats.jumut.ch/version.json                  # {"commit": "abc1234", ...}
```

## 5. Auto-Deploy testen

1. Auf GitHub eine kleine Änderung auf `main` committen, z.B. in `tarife.toml` bei einem
   geprüften Eintrag `verified = true` setzen (Stift-Symbol → „Commit changes“).
2. Nach ≤ 2 Minuten:
   * A/B: `journalctl -u ladestatistik-autodeploy -n 20 --no-pager` →
     `autodeploy: deployt: abc1234 – …`
   * C: Add-on-Protokoll → `deployt: abc1234 – …`
3. `https://stats.jumut.ch/version.json` bzw. der Footer im Dashboard („Version abc1234“)
   zeigt den neuen Commit (Browser-Cache max. 5 min).

Was bei einem Push passiert: `git fetch` → Wechsel auf den neuen Commit → Unit-Tests und
Probe-Dashboard → bei Erfolg Dienste neu starten (A: geänderte systemd-Units werden mit
installiert; B: `docker compose up -d --build`; C: Prozesse im Add-on neu starten) → bei
Fehler zurück auf den alten Stand; der fehlerhafte Commit wird gemerkt und nicht erneut
versucht, bis ein neuer Push kommt.

**Wichtig:** Auf dem Pi keine versionierten Dateien direkt ändern – lokale Änderungen
blockieren das Auto-Deploy (Meldung „lokale Änderungen … Deploy abgebrochen“). Einstellungen
gehören in `config.toml` (nicht versioniert), Preise über GitHub in `tarife.toml`.

## 6. Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| `stats.jumut.ch` → Fehler 502 / „Bad gateway“ | Tunnel erreicht den Webserver nicht | Auf dem Pi `curl -sI http://127.0.0.1:8099/`; Service-URL im Tunnel prüfen; HA: IP statt `local-ladestatistik` |
| Fehler 1033 | Tunnel offline | läuft `cloudflared` bzw. das Cloudflared-Add-on? |
| Weiterleitung auf `jumut.cloudflareaccess.com` | Access-Applikation greift | gewollt? sonst Wildcard-Applikation anpassen |
| DNS „record already exists“ | alter `stats`-Eintrag | Eintrag löschen, Hostname erneut speichern |
| Auto-Deploy tut nichts | keine neuen Commits auf dem eingestellten Branch | `/etc/default/ladestatistik` bzw. Add-on-Option `branch` |
| „lokale Änderungen … abgebrochen“ | Datei im Repo auf dem Pi geändert | `sudo -u ladestatistik git -C /opt/ladestatistik status`, Änderung zurücknehmen |
| „Prüfung fehlgeschlagen – zurück auf …“ | Tests rot oder Tarifdatei fehlerhaft | Fehler im Protokoll lesen, Korrektur pushen |
| Dashboard leer | erst wenige Minuten Daten | `health` prüfen; Kennzahlen nach einigen Stunden |
| `tariff-check` meldet Abweichung | Betreiber hat Preis geändert | neuen Eintrag mit neuem `valid_from` in `tarife.toml` |
