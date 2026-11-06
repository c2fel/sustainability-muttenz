# sustainability-muttenz – Ladestatistik Muttenz

Entscheidungsgrundlage für 1–2 öffentliche Ladestationen an der **Bahnhofstrasse 48,
4132 Muttenz**: Wie oft und wie lange sind die Ladestationen in der Nähe belegt, was
kosten sie, und wie hängt die Nutzung vom Preis ab?

Datenquelle ist [ich-tanke-strom.ch](https://www.ich-tanke-strom.ch) des Bundesamts für
Energie (BFE): die neue OCPI-API (Standorte, **Tarife**, Live-Status) und die bisherigen
OICP-Dateien (alle Betreiber). Ein Collector auf dem Raspberry Pi zeichnet den Status
laufend auf, daraus entstehen Auslastung, Ladevorgänge, Standzeiten und ein Dashboard,
das über den bestehenden Cloudflare-Tunnel publiziert werden kann.

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

# Ladepunkte im Umkreis / in der Gemeinde finden (CSV + Markdown-Tabelle)
python3 -m ladestatistik -c config.toml discover --radius 1000 --municipality

# Aufzeichnung starten (Dauerbetrieb; --once für einen Testlauf)
python3 -m ladestatistik -c config.toml collect

# Dashboard erzeugen: site/index.html + site/data/{summary.json,daily.csv,evses.csv}
python3 -m ladestatistik -c config.toml publish --days 28

# Zustand prüfen
python3 -m ladestatistik -c config.toml health

# Tests
python3 -m unittest discover -s tests
```

## Was wird ausgewertet?

* **Nahbereich (≤ 800 m):** Auslastung je Ladepunkt und Standort, Ladevorgänge pro Tag,
  Standzeiten (Median, Anteil > 4 h), Heatmap Wochentag × Stunde, Anteil der Zeit, in der
  *kein* Ladepunkt frei war (Indikator für ungedeckte Nachfrage).
* **Tarife:** Kosten von Referenz-Ladevorgängen (Einkauf 1 h, Pendler 9 h, Nacht 12 h,
  Schnellladen) inkl. Zeit- und Blockiergebühren – vergleichbar über alle Tarifmodelle.
* **Preis ↔ Auslastung (Region 15 km):** Regression, Elastizität, Preisquartile;
  Vorher/Nachher-Vergleich bei jeder beobachteten Tarifänderung.

Methodik und Grenzen: [docs/methodik.md](docs/methodik.md) ·
Datenquellen und Nutzungsbedingungen: [docs/datenquellen.md](docs/datenquellen.md)

## Betrieb auf dem Raspberry Pi

systemd, Docker Compose oder Home-Assistant-OS-Add-on, Cloudflare-Tunnel
(`ladestatistik.jumut.ch` neben `charging.jumut.ch`) und optionaler Push der Daten in
den Branch `data`: **[docs/deployment.md](docs/deployment.md)**

## Aufbau

```
ladestatistik/
  sources.py     OCPI-API + OICP-Dateien (BFE)
  catalog.py     einheitlicher Ladepunkt-Katalog, Distanz, Gemeindegrenze
  geo.py         swisstopo: Geokodierung, Gemeindepolygon
  tariffs.py     OCPI-Tarifrechner, Klartext, Kennzahlen
  collector.py   Polling-Schleife -> SQLite (Status-Intervalle, Tarifversionen)
  analyze.py     Auslastung, Ladevorgänge, Heatmap, Preis-Analyse
  publish.py     statisches Dashboard + CSV/JSON
  templates/dashboard.html
deploy/          systemd, Docker, Home-Assistant-Add-on, cloudflared, git-publish.sh
docs/            Standorte, Datenquellen, Methodik, Betrieb
tests/           Unit-Tests (unittest)
```

## Nächste Schritte

1. Collector auf dem Pi installieren und 4–8 Wochen laufen lassen.
2. Tarife von IWB, Coop/Energie 360° und Migros in der App ablesen und als
   `[[manual_tariff]]` erfassen (bis das BFE sie liefert).
3. Vor einer öffentlichen Publikation die kommerzielle Nutzung beim BFE abklären
   (ich-tanke-strom@bfe.admin.ch).
4. Später: eigene Ladepunkte über EVCC steuern und deren Sitzungen (EVCC-API) mit der
   Umgebung vergleichen.

Datenquelle: ich-tanke-strom.ch, Bundesamt für Energie BFE.
