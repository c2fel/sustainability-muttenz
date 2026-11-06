# Ladepunkte rund um die Bahnhofstrasse 48, Muttenz

Stand: **6. November 2026, 04:15 UTC**. Quelle: ich-tanke-strom.ch (BFE), OCPI-API und
OICP-Dateien. Standort: Bahnhofstrasse 48, 4132 Muttenz (amtliche Gebäudeadresse
47.531982 N / 7.649472 E). Distanzen sind Luftlinie.

Vollständige Liste (alle 49 Ladepunkte in der Gemeinde Muttenz, inkl. Koordinaten und
OCPI-Schlüssel): [`data/discovery/2026-11-06_muttenz.csv`](../data/discovery/2026-11-06_muttenz.csv)
Neu erzeugen: `python -m ladestatistik discover --radius 1000 --municipality`

## Nahbereich (≤ 800 m): 5 Standorte, 11 Ladepunkte

Diese Ladepunkte sind im Collector als **Fokus** gesetzt (`focus_radius_m = 800`).

| # | Distanz | Standort | EVSE-ID | OCPI `party/location/evse_uid` | Leistung | Zugang (OICP) | Öffnung | Tarif inkl. 8.1 % MWST |
|---|---:|---|---|---|---|---|---|---|
| 1 | 224 m | **Eotec AG**, Hardstrasse 21 | `CH*SUI*E31283` | `CH/SUI/46875/147386` | 22 kW AC, Typ 2 | eingeschränkt | 24/7 | 0.39 CHF/kWh + 1.20 CHF/h |
| | | | `CH*SUI*E31284` | `CH/SUI/46875/147384` | 22 kW AC, Typ 2 | eingeschränkt | 24/7 | 0.39 CHF/kWh + 1.20 CHF/h |
| 2 | 249 m | **Ageba Treuhand AG**, Hofackerstrasse 3 | `CH*SUI*E30985` | `CH/SUI/43981/147374` | 11 kW AC, Typ 2 | eingeschränkt | 24/7 | 0.35 CHF/kWh + 1.81 CHF/h |
| 3 | 540 m | **IWB**, Jakob-Eglin-Strasse / Hauptstrasse 80 | `CH*IWB*E55318` | `CH/IWB/47020/148231` | 22 kW AC, Typ 2 | öffentlich | 24/7 | 0.48 CHF/kWh, keine Blockiergebühr² |
| | | | `CH*IWB*E55319` | `CH/IWB/47020/148233` | 22 kW AC, Typ 2 | öffentlich | 24/7 | dito² |
| 4 | 561 m | **Coop Muttenz Dorf** (Energie 360°/JOYA), Brühlweg 8 | `CH*360*E88149` | `CH/360/44187/149312` | 22 kW AC, Typ 2 | öffentlich | Mo–Fr 08–20, Sa 07:30–20 | 0.39 CHF/kWh² |
| | | | `CH*360*E88150` | `CH/360/44187/149314` | 22 kW AC, Typ 2 | öffentlich | dito | dito |
| | | | `CH*360*E88186` | `CH/360/44187/149328` | 22 kW AC¹, Typ 2 | öffentlich | dito | dito |
| | | | `CH*360*E88187` | `CH/360/44187/149325` | 22 kW AC¹, Typ 2 | öffentlich | dito | dito |
| 5 | 770 m | **Migros Muttenz**, Rothausstrasse (M-Charge) | `CH*MIG*E*246815` | – (nur OICP) | 22 kW AC, Typ 2 | öffentlich, Parkplatz kostenpflichtig | Ladenöffnung | 0.38 CHF/kWh² |
| | | | `CH*MIG*E*246816` | – (nur OICP) | 22 kW AC, Typ 2 | dito | dito | dito² |

¹ in der OCPI-API als `AC_1_PHASE` mit 22 kW gemeldet – vermutlich ein Datenfehler des Betreibers.

² Ad-hoc-Preis aus der Website des Betreibers (Recherche 6.11.2026), erfasst in
[`tarife.toml`](../tarife.toml) mit `verified = false` – vor Ort prüfen. Quellen und
Belastbarkeit: [datenquellen.md](datenquellen.md#tarife-ohne-api-webscraping-und-manuelle-erfassung).
Die Preise 1 und 2 stammen aus der BFE-API; dort ist die MWST-Angabe möglicherweise falsch
(dann 0.36 bzw. 0.32 CHF/kWh brutto) – ebenfalls prüfen.

**Zugang** ist das OICP-Feld `Accessibility`: *eingeschränkt* = „Restricted access“ (z.B.
Firmenparkplatz, evtl. nur ausserhalb der Bürozeiten nutzbar), *öffentlich* = „Free
publicly accessible“ (frei zugänglich – nicht gratis!). Vor Ort prüfen, ob die beiden
Swisscharge-Standorte (1, 2) tatsächlich frei angefahren werden können.

### Die 2–4 relevantesten Standorte

1. **Hardstrasse 21 (224 m)** und **Hofackerstrasse 3 (249 m)** – nächste Konkurrenz,
   gleicher Typ wie eine eigene Station (AC, Swisscharge-Plattform, Gastgeber-Tarif).
   Tarife sind vollständig in der API → ideal für den Preisvergleich.
2. **IWB Hauptstrasse 80 (540 m)** – einzige rund um die Uhr öffentlich zugängliche
   Station in Gehdistanz zum Bahnhof.
3. **Coop Muttenz Dorf (561 m)** – 4 Ladepunkte, aber nur zu Ladenöffnungszeiten
   (keine Konkurrenz für Pendler- oder Nachtladen).

Am Bahnhof Muttenz selbst (SBB-Parkplatz/P+R) ist **kein** öffentlicher Ladepunkt
gemeldet.

## Knapp ausserhalb (800–900 m)

| Distanz | Standort | Ladepunkte | Hinweis |
|---:|---|---|---|
| 825–854 m | Abt Automobile AG, St. Jakobs-Strasse 72/80 (eCarUp) | 8× AC 22 kW, 2× DC 180 kW | Garage; 4 von 8 AC-Punkten aktuell „OutOfService“; Preis offen (nur App/QR) |
| 826 m | Shell, Hofackerstrasse 30 (Shell Recharge) | 2× AC 22 kW, DC 44 kW, DC 22 kW | Tankstelle, eingeschränkter Zugang; ad hoc ab 0.69 (≤ 22 kW) / 0.79 CHF/kWh (> 22 kW) |

## Übrige Gemeinde Muttenz (> 1 km)

IWB Hauptstrasse 2 (2 × 22 kW, 1.06 km) · IWB Grendelweg/Hallenbad (2 × 22 kW, 1.13 km) ·
MOVE Infrapark Rothausstrasse 61 (2 × 22 kW, 1.19 km) · MOVE Rennbahnklinik (2 × 22 kW,
1.21 km) · AVIA Birsfelderstrasse 44 (3 × 22 kW, 1.24 km) · IWB Lutzertstrasse 33
(2 × 22 kW, 1.28 km) · MOVE Hofackerstrasse 72 (2 × 22 kW, 1.34 km) · Coop Freidorf
(2 × 22 kW, 1.71 km) · IWB Waldhaus „In der Hard“ (DC 24 kW + AC 22 kW, 1.73 km) ·
MOVE/Primeo Vitra Klünenfeldstrasse 22 (4 × 11 kW, 1.94 km).

**Total Gemeinde Muttenz:** 49 Ladepunkte an 18 Standorten (davon 6 DC), Gemeindegrenze
gemäss swisstopo (BFS-Nr. 2770).

## Datenabdeckung

| Betreiber | Status live | Tarif |
|---|---|---|
| Swisscharge (CH\*SUI) | ✔ OCPI + OICP | BFE-API |
| IWB (CH\*IWB) | ✔ OCPI + OICP | `tarife.toml` (Website IWB), API-Tarif fehlt noch |
| Energie 360°/Coop (CH\*360) | ✔ OCPI + OICP | `tarife.toml` (Website Energie 360°), API-Tarif fehlt noch |
| Migros M-Charge, Shell | ✔ nur OICP (2-min-Raster) | `tarife.toml` (Websites Migrol, Shell) |
| MOVE, eCarUp, AVIA VOLT | ✔ nur OICP (2-min-Raster) | offen – nur an der Station / in der App |

Die OCPI-API des BFE ist erst seit Ende Oktober 2026 in Betrieb; weitere Betreiber und
Tarife kommen laufend dazu. Der Collector übernimmt neue Tarife automatisch (Katalog-
Update alle 6 h). Bis dahin stehen die Tarife in [`tarife.toml`](../tarife.toml): 12 von
20 Einträgen sind per Webscraping/Recherche befüllt (ungeprüft), 8 sind offen (eCarUp,
MOVE, AVIA VOLT), siehe [datenquellen.md](datenquellen.md).

## Überwachung

Der Collector zeichnet **alle 49 Ladepunkte der Gemeinde** auf. Die 11 Ladepunkte im
Nahbereich erscheinen im Dashboard zusätzlich mit Steckbrief pro Standort, Heatmap,
Standzeiten-Verteilung und 7-Tage-Verlauf:
<https://stats.jumut.ch/reports/charging/>
