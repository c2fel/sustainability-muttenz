# Datenquellen

## 1. ich-tanke-strom.ch – OCPI-API (BFE, ab November 2026)

Offizielle Schnittstelle des Bundesamts für Energie. Keine Authentifizierung.
Doku: <https://github.com/SFOE/ichtankestrom_Documentation>

| Endpunkt | Inhalt | Nutzung im Collector |
|---|---|---|
| `GET /ocpi/locations` | Standorte, EVSEs, Stecker, `tariff_ids`, Öffnungszeiten | alle 6 h (2 Seiten à 1000) |
| `GET /ocpi/tariffs` | Tarife (OCPI 2.3): Energie-, Zeit-, Park-, Grundpreis, Zeitfenster, MWST | alle 6 h (3 Seiten) |
| `GET /ocpi/status?date_from=…` | aktueller Status aller EVSEs, die seit `date_from` eine Meldung hatten | alle 60 s (Delta) + alle 15 min (Vollabzug mit `date_from=2000-01-01`) |
| `GET /ocpi/status/{cc}/{party}/{loc}/evses/{uid}` | Status eines EVSE | für Einzelabfragen |

Basis-URL: `https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi`

Wichtig:
* Die API liefert **keine Historie** – nur den jeweils letzten Status mit `last_updated`.
  Die Belegungsstatistik entsteht erst durch laufendes Aufzeichnen (Collector).
* Status-Werte: `AVAILABLE`, `CHARGING`, `BLOCKED`, `RESERVED`, `OUTOFORDER`,
  `INOPERATIVE`, `UNKNOWN`, `PLANNED`, `REMOVED`. `CHARGING` heisst „in Benutzung“
  (Fahrzeug eingesteckt) – auch wenn es schon voll ist.
* Abdeckung (6.11.2026): 1430 Standorte / 4803 EVSEs von Swisscharge, Energie 360°,
  IWB, GOFAST, ewz. 2627 Tarife, aber v.a. von Swisscharge; IWB- und Energie-360°-Stationen
  in Muttenz referenzieren Tarif-IDs, die (noch) nicht ausgeliefert werden.
* Rate-Limit laut Doku „z.B. 60 Requests/Minute“. Der Collector braucht < 2/min.
* Tarifpreise sind meist **exkl. MWST** (`tax_included: "NO"`, `vat: 8.1`). Das Tool
  rechnet überall mit Bruttopreisen.

## 2. ich-tanke-strom.ch – OICP-Dateien (bisheriger Zugang)

Deckt **alle** gemeldeten Betreiber ab (21 054 EVSEs), aber ohne Tarife und ohne
Zeitstempel pro EVSE. Aktualisierung alle 30–60 s.

* statisch: `https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json` (1.1 MB gzip)
* Status: `https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json` (180 kB gzip)

Für MOVE, eCarUp, Migros, Shell, AVIA usw. ist das zurzeit die einzige Quelle. Die
BFE-Doku kennzeichnet diesen Zugang als „alt“; falls er abgeschaltet wird, läuft der
Collector mit der OCPI-API weiter (Fehler einer Quelle sind nicht fatal).

Hinweis: Einige EVSE-IDs kommen in der OICP-Datei doppelt vor (z.B. unter „Move“ und
„Energie 360 Grad AG“). Der Katalog dedupliziert nach EVSE-ID.

## 3. swisstopo (geo.admin.ch)

* Geokodierung der Adresse: `SearchServer` (amtliches Gebäudeadressverzeichnis)
* Gemeindegrenze Muttenz (BFS 2770): Layer `ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill`
  → bestimmt, welche Ladepunkte „in der Gemeinde“ liegen (Postleitzahlen sind dafür
  unzuverlässig: Vitra Klünenfeldstrasse hat PLZ 4127 Birsfelden, liegt aber in Muttenz).

## Nutzungsbedingungen

ich-tanke-strom.ch: *Open use. Must provide the source. Use for commercial purposes
requires permission of the data owner.*

* Quelle angeben: „Datenquelle: ich-tanke-strom.ch, Bundesamt für Energie BFE“ (steht
  im Dashboard-Footer).
* Die Analyse dient einer Investitionsentscheidung eines Unternehmens → das kann als
  kommerzielle Nutzung gelten. **Empfehlung:** kurze Anfrage an
  [ich-tanke-strom@bfe.admin.ch](mailto:ich-tanke-strom@bfe.admin.ch), bevor
  Auswertungen öffentlich publiziert werden.

## Tarife ohne API: Webscraping und manuelle Erfassung

In Muttenz liefert die BFE-API zurzeit nur für 3 von 49 Ladepunkten einen Tarif
(Swisscharge-Gastgeber). Für die übrigen Standorte wurden am **6.11.2026** die Websites der
Betreiber ausgewertet und die Ergebnisse in [`tarife.toml`](../tarife.toml) eingetragen –
jeweils mit `source`, `url`, `confidence`, `note` und `verified = false`.

**Regel:** Es gilt immer der **Ad-hoc-Preis** – ohne Abo, ohne Konto/App (Kreditkarte, TWINT,
QR-Code oder Terminal an der Station). Wo nur App-/Konto-Preise publiziert sind, bleibt der
Eintrag offen und der App-Preis steht nur als Referenz im Kommentar.

| Betreiber (Muttenz) | Ad-hoc-Preis inkl. MWST | Quelle | Belastbarkeit |
|---|---|---|---|
| IWB, 5 Standorte AC | 0.48 CHF/kWh, keine Blockiergebühr | [IWB „Allmend Basel-Stadt“](https://www.iwb.ch/servicecenter/oeffentliches-ladenetz/mobilitaet-tarife) | mittel: publiziert für Basel-Stadt; Muttenz nutzt laut BFE-API dieselbe Tarif-ID `179904` |
| IWB Waldhaus DC 24 kW | 0.60 CHF/kWh, ab 150 min 15 Rp./min | dito, „DC bis 50 kW“ | mittel: gleiche Tarif-ID `179908` wie Basler Allmend-DC |
| Coop Muttenz Dorf / Freidorf (Energie 360°/Joya) | 0.39 CHF/kWh | [Energie 360° Easycharge](https://www.energie360.ch/de/leistungen/mobilitaet/easycharge/) | mittel: Coop-Preis ohne Unterscheidung ad hoc/registriert; Blockiergebühr unklar (nicht eingetragen) |
| Migros M-Charge | 0.38 CHF/kWh (< 22 kW) | [Migrol M-Charge](https://www.migrol.ch/migros-aufladen) | hoch: Tabelle gilt laut Seite auch „ohne Konto“ per QR-Code |
| Shell (ehem. evpass) AC 22 kW / DC 22 kW | ab 0.69 CHF/kWh | [Shell Ladetarife](https://www.shell.ch/de_ch/laden/ladetarife-fuer-ihr-elektroauto.html), Modell „Ohne App: QR-Code oder Zahlungsterminal“ | mittel: „ab“-Preis |
| Shell DC 44 kW | ab 0.79 CHF/kWh | dito (> 22 kW) | mittel |
| eCarUp (Abt Automobile, 3 Einträge) | **offen** | Preis legt der Gastgeber fest; nur in der App bzw. auf der QR-Seite an der Station | – |
| MOVE/Joya (4 Standorte) | **offen** | kein Ad-hoc-Preis publiziert; Referenz „MOVE light“ (mit Konto) AC ab 0.57 | – |
| AVIA VOLT (Trimag) | **offen** | Preis legt der Gastgeber fest; nur in der AVIA-VOLT-App | – |

Nicht verwendbare Quellen: Swisscharge listet [Roaming-Preise](https://swisscharge.ch/en/solutions/charging-prices/)
anderer Netze für Swisscharge-Kunden (nicht ad hoc); parking.ch und Electromaps spiegeln nur die
BFE-Stammdaten ohne Preis; die Shell-Recharge-Karten-API ist aus der Cloud-Umgebung gesperrt
(auf dem Pi evtl. erreichbar, aber App-Preise, nicht ad hoc).

### Prüfen

1. Vor Ort bzw. in der App den Ad-hoc-Preis kontrollieren (QR-Code scannen zeigt den Preis vor
   der Zahlung), bei Abweichung Preis korrigieren, dann `verified = true` setzen.
2. Offene Einträge (eCarUp, MOVE, AVIA VOLT) an der Station per QR-Code erfassen.
3. `python -m ladestatistik -c config.toml health` zeigt, wie viele Einträge noch ungeprüft sind;
   das Dashboard markiert sie mit „manuell, ungeprüft“.

### Preis-Watcher (wiederholtes Webscraping)

`python -m ladestatistik -c config.toml tariff-check` ruft die vier ergiebigen Quellen ab
(Migrol, Energie 360°, IWB, Shell), speichert einen Snapshot unter `data/pricewatch/` und
vergleicht mit den Einträgen in `tarife.toml`, die ein `watch`-Feld haben. Bei einer
Abweichung (Exit-Code 1) einen **neuen** Eintrag mit neuem `valid_from` erfassen – so fliesst
die Preisänderung in die Vorher/Nachher-Auswertung ein. Der Watcher schreibt nie selbst in
`tarife.toml`. Ändert ein Betreiber das Seitenlayout, meldet der Check einen Fehler statt
eines falschen Preises. Betrieb: täglich per systemd-Timer, Docker-Dienst `pricewatch` oder im
Home-Assistant-Add-on (siehe [deployment.md](deployment.md)). Last: 4 Seitenabrufe pro Tag.

### MWST in der BFE-API prüfen

Der Joya-Feed meldet Tarife mit `tax_included: "NO"` und `vat: 8.1`. Für die Coop-DC-Tarif-ID
`6962` ergibt das 0.55 CHF/kWh exkl. = 0.59 inkl. MWST; Energie 360° publiziert für Coop-DC
aber 0.55 **inkl.** MWST. Die Zeitpreise im Feed (4.44, 2.78, 1.11 CHF/h) ergeben dagegen mit
MWST genau runde Beträge (4.80, 3.00, 1.20). Möglicherweise sind die Energiepreise im Feed
bereits brutto. Betroffen wären auch die drei API-Tarife im Nahbereich (Hardstrasse 21:
0.36 vs. 0.39 CHF/kWh; Hofackerstrasse 3: 0.32 vs. 0.35 CHF/kWh) – bei der Prüfung vor Ort
mitkontrollieren. Ist der API-Preis falsch, einen manuellen Eintrag erfassen (hat Vorrang).

### Webscraping und Nutzungsbedingungen

Abgerufen werden nur öffentliche Preisseiten, einzeln und selten (Erstrecherche einmalig,
Watcher 4 Abrufe pro Tag), mit identifizierbarem User-Agent. Apps und geschützte Bereiche
(eCarUp, AVIA VOLT, Joya-App) werden nicht automatisiert abgefragt; viele Apps verbieten das
in ihren Nutzungsbedingungen.
