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

## Lücken und Phase 2 (Tarife ohne API)

Für Stationen ohne API-Tarif (in Muttenz: IWB, Coop/Energie 360°, Migros, MOVE, eCarUp,
Shell, AVIA):

1. **Manuell erfassen** (sofort, zuverlässig): Preis in der jeweiligen App ablesen
   (Swisscharge/JOYA, IWB, Migros, MOVE, eCarUp) und in `config.toml` als
   `[[manual_tariff]]` mit Quelle und Datum eintragen. Bei 5–10 Standorten ist das
   weniger Aufwand als ein Scraper, und Preise ändern selten.
2. **Abwarten**: IWB und Energie 360° liefern bereits Tarif-IDs – die Tarifobjekte
   dürften in der API nachgereicht werden. Der Collector erkennt das automatisch.
3. **Webscraping** (nur falls nötig): vorher Nutzungsbedingungen der jeweiligen
   Plattform prüfen; viele Apps verbieten automatisierte Abfragen. Ein Scraper wäre ein
   eigenes Modul, das Tarife im OCPI-Format liefert – die Kostenrechnung und Auswertung
   bleiben unverändert.
