# sustainability-muttenz – Ladestatistik Muttenz

Entscheidungsgrundlage für 1–2 öffentliche Ladestationen an der **Bahnhofstrasse 48,
4132 Muttenz**: Wie oft und wie lange sind die Ladestationen in der Nähe belegt, was
kosten sie, und wie hängt die Nutzung vom Preis ab?

Datenquelle ist [ich-tanke-strom.ch](https://www.ich-tanke-strom.ch) des Bundesamts für
Energie (BFE): die neue OCPI-API (Standorte, **Tarife**, Live-Status) und die bisherigen
OICP-Dateien (alle Betreiber). Ein Collector auf dem Raspberry Pi zeichnet den Status
**aller Ladepunkte in der Gemeinde Muttenz** laufend auf; die Standorte in unmittelbarer
Nähe (≤ 800 m) werden einzeln im Detail ausgewertet. Fehlende Preise werden manuell in
[`tarife.toml`](tarife.toml) erfasst. Das Dashboard erscheint unter
**`https://stats.jumut.ch/reports/charging/`** (über den bestehenden Cloudflare-Tunnel).

## Schritt 1: Ladepunkte in der Nähe (Stand 6.11.2026)

| Distanz | Standort | EVSE-IDs | Tarif (inkl. MWST) |
|---:|---|---|---|
| 224 m | Eotec AG, Hardstrasse 21 (Swisscharge) | `CH*SUI*E31283`, `CH*SUI*E31284` (2 × 22 kW) | 0.39 CHF/kWh + 1.20 CHF/h |
| 249 m | Ageba Treuhand AG, Hofackerstrasse 3 (Swisscharge) | `CH*SUI*E30985` (11 kW) | 0.35 CHF/kWh + 1.81 CHF/h |
| 540 m | IWB, Jakob-Eglin-Strasse / Hauptstrasse 80 | `CH*IWB*E55318`, `CH*IWB*E55319` (2 × 22 kW) | noch nicht in der API |
| 561 m | Coop Muttenz Dorf, Brühlweg 8 (Energie 360°) | `CH*360*E88149`, `…E88150`, `…E88186`, `…E88187` (4 × 22 kW) | noch nicht in der API |
| 770 m | Migros Muttenz, Rothausstrasse (M-Charge) | `CH*MIG*E*246815`, `CH*MIG*E*246816` (2 × 22 kW) | keine Tarifdaten |

Details, OCPI-Schlüssel, Zugänglichkeit und alle 49 Ladepunkte der Gemeinde:
**[docs/standorte-muttenz.md](docs/standorte-muttenz.md)** ·
CSV: [data/discovery/2026-11-06_muttenz.csv](data/discovery/2026-11-06_muttenz.csv)

## Schnellstart

Python ≥ 3.11, keine weiteren Abhängigkeiten.

```bash
cp config.example.toml config.toml

# Ladepunkte in der Gemeinde finden (CSV + Markdown-Tabelle)
python3 -m ladestatistik -c config.toml discover

# Aufzeichnung starten (Dauerbetrieb; --once für einen Testlauf)
python3 -m ladestatistik -c config.toml collect

# Web-Root erzeugen: site/index.html + site/reports/charging/{index.html,data/*}
python3 -m ladestatistik -c config.toml publish --days 28

# Web-Root ausliefern (http://127.0.0.1:8099/reports/charging/)
python3 -m ladestatistik -c config.toml serve

# Zustand prüfen (inkl. welche Tarife noch fehlen)
python3 -m ladestatistik -c config.toml health

# neue Stationen ohne Tarif in tarife.toml ergänzen
python3 -m ladestatistik -c config.toml tariff-template --out tarife.toml

# Tests
python3 -m unittest discover -s tests
```

## Was wird ausgewertet?

* **Nahbereich (≤ 800 m, 5 Standorte / 11 Ladepunkte):** Steckbrief pro Standort
  (Betreiber, Eigentümer, Zugang, Öffnungszeiten, Tarif, OCPI-IDs), Auslastung,
  Ladevorgänge pro Tag, Standzeiten-Verteilung, Heatmap Wochentag × Stunde, Anteil der
  Zeit ohne freien Ladepunkt und ein 7-Tage-Verlauf pro Ladepunkt.
* **Gemeinde Muttenz (18 Standorte / 49 Ladepunkte):** Vergleichstabelle mit Auslastung,
  Standzeiten und Tarifen.
* **Tarife:** Kosten von Referenz-Ladevorgängen (Einkauf 1 h, Pendler 9 h, Nacht 12 h)
  inkl. Zeit- und Blockiergebühren – vergleichbar über alle Tarifmodelle.
* **Preis ↔ Auslastung:** Vergleich der Muttenzer Standorte und Vorher/Nachher-Vergleich
  bei jeder Tarifänderung (BFE-API oder neuer Eintrag in `tarife.toml`).

Methodik und Grenzen: [docs/methodik.md](docs/methodik.md) ·
Datenquellen und Nutzungsbedingungen: [docs/datenquellen.md](docs/datenquellen.md)

## Betrieb und Veröffentlichung

systemd, Docker Compose oder Home-Assistant-OS-Add-on; Veröffentlichung unter
`stats.jumut.ch` (Übersicht `/`, Ladestatistik `/reports/charging/`, Platz für `/api/v1/…`),
Zugriffsschutz pro Pfad und optionaler Push der Daten in den Branch `data`:
**[docs/deployment.md](docs/deployment.md)**

## Aufbau

```
ladestatistik/
  sources.py     OCPI-API + OICP-Dateien (BFE)
  catalog.py     einheitlicher Ladepunkt-Katalog, Distanz, Gemeindegrenze
  geo.py         swisstopo: Geokodierung, Gemeindepolygon
  tariffs.py     OCPI-Tarifrechner, Klartext, Kennzahlen
  collector.py   Polling-Schleife -> SQLite (Status-Intervalle, Tarifversionen)
  analyze.py     Auslastung, Ladevorgänge, Heatmap, Preis-Analyse
  publish.py     Web-Root: Übersicht + reports/charging/ (Dashboard, CSV/JSON)
  serve.py       statischer Webserver für stats.jumut.ch (Cache-Header, kein Listing)
  templates/dashboard.html
tarife.toml      manuell erfasste Tarife (Preisverlauf, versioniert)
deploy/          systemd, Docker, Home-Assistant-Add-on, cloudflared, git-publish.sh
docs/            Standorte, Datenquellen, Methodik, Betrieb
tests/           Unit-Tests (unittest)
```

## Nächste Schritte

1. Collector auf dem Pi installieren und 4–8 Wochen laufen lassen.
2. Offene Tarife in [`tarife.toml`](tarife.toml) erfassen (19 Einträge: IWB, Coop/Energie
   360°, Migros, MOVE, eCarUp, Shell, AVIA).
3. `stats.jumut.ch` im bestehenden Tunnel anlegen und Zugriff festlegen (öffentlich oder
   Cloudflare Access). Vor einer öffentlichen Publikation die kommerzielle Nutzung beim
   BFE abklären (ich-tanke-strom@bfe.admin.ch).
4. Später: eigene Ladepunkte über EVCC steuern und deren Sitzungen (EVCC-API) mit der
   Umgebung vergleichen; API unter `stats.jumut.ch/api/v1/…`.

Datenquelle: ich-tanke-strom.ch, Bundesamt für Energie BFE.
