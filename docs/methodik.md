# Methodik

## Umfang

* **Gemeinde Muttenz:** Aufgezeichnet werden alle Ladepunkte innerhalb der
  Gemeindegrenze gemäss swisstopo (BFS-Nr. 2770) – zurzeit 49 Ladepunkte an 18 Standorten.
  Die Postleitzahl ist dafür ungeeignet (z.B. liegt Vitra, PLZ 4127 Birsfelden, in Muttenz).
* **Nahbereich (≤ 800 m Luftlinie):** 5 Standorte / 11 Ladepunkte mit Detailauswertung
  pro Standort (Steckbrief, Heatmap, Standzeiten, 7-Tage-Verlauf). Erweiterbar über
  `focus_radius_m` oder `focus_evse_ids`.
* Optional lässt sich zusätzlich ein Umkreis aufzeichnen (`record_radius_km`, Standard 0).

## Aufzeichnung

Der Collector speichert den Status jedes Ladepunkts als **Intervalle**
(`status_run`: Ladepunkt, Quelle, Status, Beginn, Ende).

* OCPI: Statuswechsel werden mit dem Zeitstempel `last_updated` des Betreibers
  verbucht (sekundengenau). Ein erfolgreicher Delta-Abruf ohne Meldung verlängert das
  laufende Intervall.
* OICP: Abruf alle 120 s, Wechsel werden zum Abrufzeitpunkt verbucht (±1 min).
* Fällt der Collector länger als `max_gap_s` (10 min) aus, entsteht eine **Lücke**
  statt eines erfundenen Status. Lücken zählen weder als frei noch als belegt.
* Pro Ladepunkt wird OCPI bevorzugt, sonst OICP. Bei Ladepunkten mit beiden Quellen
  dient OICP als Gegenprobe.

Normalisierte Zustände:

| normalisiert | OCPI | OICP |
|---|---|---|
| frei | AVAILABLE | Available |
| belegt | CHARGING, BLOCKED | Occupied |
| reserviert | RESERVED | Reserved |
| ausser Betrieb | OUTOFORDER, INOPERATIVE | OutOfService |
| unbekannt | UNKNOWN | Unknown |

## Kennzahlen

| Kennzahl | Definition |
|---|---|
| **Auslastung** | belegte Zeit ÷ betriebsbereite Zeit (frei + belegt + reserviert) |
| **Verfügbarkeit** | betriebsbereite Zeit ÷ (betriebsbereit + ausser Betrieb) |
| **Ladevorgang** | zusammenhängende Belegung; Unterbrüche < 3 min werden zusammengefasst, Belegungen < 5 min verworfen |
| **Standzeit** | Dauer eines Ladevorgangs (Einstecken bis Ausstecken – nicht nur die Ladezeit) |
| **Vollbelegung** | Anteil der Minuten, in denen an einem Standort (bzw. im ganzen Nahbereich) *kein* Ladepunkt frei war – ein Indikator für ungedeckte Nachfrage |
| **Heatmap** | Auslastung je Wochentag × Stunde (Lokalzeit Europe/Zurich) |

## Tarife vergleichbar machen

Tarife bestehen aus bis zu vier Komponenten (CHF/kWh, CHF/h, CHF/h Parkieren,
Grundgebühr), mit Zeitfenstern („Blockiergebühr ab 4 h, 08–20 Uhr“). Ein einzelner
„Preis pro kWh“ wäre irreführend. Deshalb werden die Kosten typischer
**Referenz-Ladevorgänge** berechnet (inkl. MWST, konfigurierbar in `config.toml`):

| ID | Szenario | Dauer | Energie | Leistung |
|---|---|---|---|---|
| kurz | Einkauf, Sa 10:00 | 1 h | 10 kWh | max. 11 kW |
| pendler | Bahnpendler, Di 07:00 | 9 h | 25 kWh | max. 11 kW |
| nacht | Anwohner, Mi 19:00 | 12 h | 30 kWh | max. 11 kW |
| schnell | Schnellladen, Do 14:00 | 30 min | 25 kWh | max. 150 kW |

Beispiel 6.11.2026: Hardstrasse 21 (0.39 CHF/kWh + 1.20 CHF/h) kostet für „kurz“
CHF 5.09 (0.51 CHF/kWh effektiv), für „pendler“ CHF 20.53 (0.82 CHF/kWh effektiv). Die
Zeitgebühr verteuert lange Standzeiten stark – für einen Standort beim Bahnhof
(Pendler) ist das der entscheidende Tarifparameter.

Die Kostenrechnung folgt OCPI 2.2.1/2.3.0 (erstes passendes Tarif-Element pro
Dimension, Restriktionen, `step_size`). Abweichung: `TIME` gilt standardmässig für die
ganze Anschlussdauer (`time_mode = "session"`), weil Schweizer Betreiber Zeit- und
Blockiergebühren so verwenden. Mit `time_mode = "charging"` wird die Spezifikation
strikt angewendet.

## Preis ↔ Auslastung

Ziel: Aussagen wie „ab Preis X wird eine Station Y % weniger genutzt“. Grundlage sind die
Tarife aus der BFE-API und die manuell erfassten Tarife in `tarife.toml`.

1. **Vergleich der Standorte in Muttenz** (Querschnitt): alle AC-Ladepunkte mit Tarif und
   ≥ 3 Tagen Beobachtung. Ausgewiesen werden lineare Regression (Prozentpunkte Auslastung
   je 10 Rp./kWh), Korrelation r, Preiselastizität (log-log) und – ab 8 Ladepunkten – die
   mittlere Auslastung je Preisquartil.
   *Achtung:* Mit ~40 AC-Ladepunkten an ~16 Standorten ist das eine kleine Stichprobe,
   und Ladepunkte am selben Standort sind nicht unabhängig. Lage, Zugänglichkeit
   (Firmenparkplatz vs. öffentlich) und Öffnungszeiten (Coop/Migros) beeinflussen die
   Auslastung stark. Die Zahlen beschreiben Muttenz, sie beweisen keinen Preiseffekt.
   Hilfreich ist der Vergleich ähnlicher Standorte (öffentlich, 24/7, 22 kW AC).

2. **Vorher/Nachher** (belastbarer): Ändert ein Betreiber den Tarif, vergleicht das Tool
   die Auslastung desselben Ladepunkts 14 Tage vor und nach der Änderung. Standort und
   Hardware bleiben gleich, damit ist der Preiseffekt viel sauberer isoliert. Erkannt
   werden neue Tarifversionen aus der BFE-API und neue Einträge in `tarife.toml` (gleiche
   `evse_ids`, späteres `valid_from`). Saisoneffekte (Ferien, Wetter) über die übrigen
   Muttenzer Ladepunkte ohne Preisänderung kontrollieren (Differenz-in-Differenzen),
   sobald mehrere Änderungen beobachtet wurden.

Zusätzlich: **Standzeit mit vs. ohne Zeitgebühr** – zeigt, ob Blockier-/Zeitgebühren
die Belegungsdauer verkürzen (wichtig für die Wirtschaftlichkeit: kürzere Standzeiten =
mehr Ladevorgänge pro Ladepunkt).

### Manuell erfasste Tarife

`tarife.toml` enthält für jeden Muttenzer Standort ohne API-Tarif einen Eintrag (AC und
DC getrennt). Preise brutto (inkl. MWST) so eintragen, wie sie in der App angezeigt werden,
mit `valid_from` und `source`. Ein manueller Tarif hat Vorrang vor der API;
`python -m ladestatistik health` zeigt, wo inzwischen ein API-Tarif vorliegt. Bei einer
Preisänderung einen **neuen** Eintrag mit neuem Datum ergänzen und den alten stehen lassen.

## Wie viele Daten braucht es?

* Heatmap/Auslastung im Nahbereich: ab ~2 Wochen aussagekräftig, 6–8 Wochen für
  saisonale Robustheit.
* Vergleich der Standorte: erst interpretieren, wenn (fast) alle Tarife erfasst sind und
  mindestens 4 Wochen Daten vorliegen.
* Vorher/Nachher: hängt davon ab, wie oft Betreiber Preise ändern – das Tool zeichnet
  jede Tarifversion auf (`tariff_version`, `tarife.toml`), damit nichts verloren geht.

## Grenzen

* Status ≠ Energie: Es ist nicht bekannt, wie viele kWh geladen wurden. Umsatz lässt
  sich nur über Annahmen (z.B. Ø 11 kW × Ladezeit) abschätzen.
* Betreiber melden Status unterschiedlich zuverlässig (z.B. viele „Unknown“ bei MOVE).
  Die Verfügbarkeit wird pro Ladepunkt ausgewiesen; Ladepunkte mit wenig Beobachtungszeit
  fallen aus der Preisanalyse.
* „Eingeschränkter Zugang“ (Firmenparkplätze) verzerrt Auslastungsvergleiche – im Zweifel
  über `exclude_evse_ids` ausschliessen.
