# Betrieb auf dem Raspberry Pi

Der Collector braucht nur Python ≥ 3.11 (keine Zusatzpakete). Er läuft dauerhaft,
das Dashboard wird alle 15 Minuten neu erzeugt und lokal auf Port 8099 ausgeliefert.
Öffentlich erreichbar wird es über den bestehenden Cloudflare-Tunnel.

```
          ich-tanke-strom.ch (BFE)
                  │  HTTPS (ausgehend, < 2 Requests/min)
┌─────────────────▼──────────────────── Raspberry Pi ─┐
│ collector ──► SQLite (data/ladestatistik.sqlite)     │
│ publish (15 min) ──► site/index.html + data/*.csv    │
│ web 127.0.0.1:8099 ◄── cloudflared ◄─────────────────┼── ladestatistik.jumut.ch
│ EVCC :7070          ◄── cloudflared ◄─────────────────┼── charging.jumut.ch (Access)
│ git-publish.sh ──► GitHub, Branch "data" (optional)  │
└──────────────────────────────────────────────────────┘
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
sudo -u ladestatistik cp config.example.toml config.toml   # anpassen
sudo -u ladestatistik mkdir -p data site
sudo -u ladestatistik python3 -m ladestatistik -c config.toml collect --once   # Test
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ladestatistik-collector ladestatistik-web ladestatistik-publish.timer
python3 -m ladestatistik -c config.toml health
```

Bei privatem Repo: zum Klonen einen Deploy-Key verwenden (siehe unten).
Update: `cd /opt/ladestatistik && sudo -u ladestatistik git pull && sudo systemctl restart ladestatistik-collector`

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
4. Konfiguration und Daten liegen in `/addon_configs/local_ladestatistik/`
   (`config.toml` wird beim ersten Start aus dem Beispiel erzeugt).
5. Dashboard: `http://<ha-ip>:8099`.

## Cloudflare-Tunnel

Es braucht **keinen neuen Tunnel** – der bestehende Tunnel für `charging.jumut.ch`
bekommt einen zweiten öffentlichen Hostnamen:

* **Im Dashboard verwalteter Tunnel** (Standard): Cloudflare Zero Trust → Networks →
  Tunnels → Tunnel wählen → *Public Hostname* → *Add*:
  Subdomain `ladestatistik`, Domain `jumut.ch`, Service `HTTP`, URL `localhost:8099`
  (Variante A/B) bzw. `local-ladestatistik:8099` oder `<ha-ip>:8099` (Variante C).
* **Home-Assistant-Add-on „Cloudflared“**: in den Add-on-Optionen unter
  `additional_hosts` ergänzen:
  ```yaml
  - hostname: ladestatistik.jumut.ch
    service: http://local-ladestatistik:8099
  ```
* **Lokal verwalteter Tunnel** (`config.yml`): siehe
  [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml).

`charging.jumut.ch` ist bereits durch **Cloudflare Access** geschützt (Login-Weiterleitung).
Für `ladestatistik.jumut.ch` bewusst entscheiden:
* intern/Team → dieselbe Access-Policy wie für EVCC anwenden;
* öffentlich → keine Access-Policy, aber vorher die BFE-Nutzungsbedingungen klären
  (siehe [datenquellen.md](datenquellen.md#nutzungsbedingungen)).

Der Webserver liefert nur statische Dateien aus (kein Schreibzugriff, keine Datenbank).

## Daten nach GitHub pushen

Ein `git push` vom Pi zu GitHub ist eine **ausgehende** Verbindung und braucht keinen
Cloudflare-Tunnel. Der Tunnel ist nur für **eingehende** Zugriffe (Dashboard, EVCC,
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
`deploy/git-publish.sh` committet höchstens einmal pro Stunde das Dashboard und die
CSV/JSON-Dateien in den separaten Branch **`data`** (nicht die SQLite-Datenbank, nicht
`main`). Der Deploy-Key gilt nur für dieses eine Repo.

Optional GitHub Pages: Settings → Pages → Branch `data`, Ordner `/docs`
(bei privaten Repos nur mit kostenpflichtigem GitHub-Plan).

### Fernwartung per SSH über den Tunnel (optional)

Public Hostname `ssh-pi.jumut.ch` → Service `SSH`, URL `localhost:22`, mit
Access-Policy. Zugriff vom Laptop: `cloudflared access ssh --hostname ssh-pi.jumut.ch`
(als `ProxyCommand` in `~/.ssh/config`). So lassen sich Updates (`git pull`) einspielen,
ohne Ports am Router zu öffnen.

## Ressourcen

| | Standard-Konfiguration (15 km Umkreis, ~1100 Ladepunkte) |
|---|---|
| Netzwerk | ca. 200 MB/Tag Download (v.a. OICP-Statusdatei alle 2 min). Mit `oicp_interval_s = 300` und `ocpi_full_interval_s = 1800` ca. 80 MB/Tag |
| Speicher | Grössenordnung einige 100 MB pro Jahr (SQLite); mit `health` beobachten |
| CPU/RAM | vernachlässigbar (< 1 s pro Abruf, < 100 MB RAM) |
| SD-Karte | Intervall-Verlängerungen werden gesammelt alle 5 min geschrieben (`flush_interval_s`) |

Backup: `sqlite3 data/ladestatistik.sqlite ".backup data/backup.sqlite"` (konsistent
auch während der Collector läuft).
