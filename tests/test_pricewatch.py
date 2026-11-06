import csv
import json
import tomllib
import unittest
from pathlib import Path

from ladestatistik import config, pricewatch

ROOT = Path(__file__).resolve().parent.parent

MIGROL = """<table><tr><td>M-Charge &lt; 64 kW</td><td>&nbsp;CHF 0.48</td></tr>
<tr><td>M-Charge &lt; 22 kW</td><td>&nbsp;CHF 0.38</td></tr></table>"""

E360 = """<p>AC</p><p>≤ 22 kW</p><p>«Slow DC»</p><p>«Fast DC»</p>
<p>Je nach Standort:</p><p>CHF 0.39/kWh (Coop-Standorte)</p>
<p>CHF 0.50/kWh 1 (Standard-Preis registrierte Swisscharge-Kunden)</p>
<p>CHF 0.55/kWh 1 (Standard-Preis ad-hoc/mit Kreditkarten/Twint)</p>
<p>Blockiergebühren</p><p>CHF 6.-/h nach 6 Stunden</p>
<p>Je nach Standort:</p><p>CHF 0.55/kWh (Coop-Standorte)</p>
<p>CHF 0.65/kWh 2 (Standard-Preis ad-hoc/mit Kreditkarten/Twint)</p>
<p>CHF 9.-/h nach 2 Stunden</p>
<p>Je nach Standort:</p><p>CHF 0.69/kWh 3 (Standard-Preis ad-hoc/mit Kreditkarten/Twint)</p>
<p>CHF 15.-/h nach 1 Stunden</p>
<p>Für charge@immo- und charge@work-Kund*innen je nach Standort:</p><p>0.39 CHF/kWh (Coop-Standorte)</p>"""

IWB = """<table><tr><td>AC</td><td>48 Rp.</td><td>Keine</td></tr>
<tr><td>DC bis 50 kW </td><td>60 Rp.</td><td>Nach 150 Minuten: 15 Rp. pro Minute</td></tr></table>"""

SHELL = json.dumps({":items": {"a": {"text": "<p>Mit Shell App &amp; Ladekarte</p><p>Ohne Abonnement</p>"
                                              "<p>≤ 22 kW</p><p>ab CHF 0.49 / kWh</p><p>&gt; 22 kW</p><p>ab CHF 0.69 / kWh</p>"},
                               "b": {"text": "<p>Ohne App</p><p>QR-Code oder Zahlungsterminal</p><p>≤ 22 kW</p>"
                                              "<p>ab CHF 0.69 / kWh</p><p>&gt; 22 kW</p><p>ab CHF 0.79 / kWh</p>"}}})


class ParserTest(unittest.TestCase):
    def test_migrol(self):
        self.assertEqual(pricewatch.parse_migrol(MIGROL), {"lt64": 0.48, "lt22": 0.38})

    def test_energie360(self):
        v = pricewatch.parse_energie360(E360)
        self.assertEqual(v["ac.coop"], 0.39)
        self.assertEqual(v["ac.adhoc"], 0.55)
        self.assertEqual(v["ac.blocking_chf_h"], 6.0)
        self.assertEqual(v["ac.blocking_after_min"], 360)
        self.assertEqual(v["dc_slow.adhoc"], 0.65)
        self.assertEqual(v["dc_fast.blocking_after_min"], 60)
        self.assertNotIn("dc_fast.coop", v)  # charge@-Block (Abo) wird nicht gelesen

    def test_iwb(self):
        v = pricewatch.parse_iwb(IWB)
        self.assertEqual(v["ac.energy"], 0.48)
        self.assertEqual(v["ac.blocking_chf_h"], 0.0)
        self.assertEqual(v["dc50.blocking_chf_h"], 9.0)
        self.assertEqual(v["dc50.blocking_after_min"], 150)

    def test_shell_takes_adhoc_model(self):
        v = pricewatch.parse_shell(SHELL)
        self.assertEqual(v["adhoc.le22"], 0.69)
        self.assertEqual(v["adhoc.gt22"], 0.79)
        self.assertEqual(v["app.le22"], 0.49)

    def test_layout_change_gives_empty_result(self):
        self.assertEqual(pricewatch.parse_migrol("<p>neues Layout</p>"), {})


class CompareTest(unittest.TestCase):
    def test_statuses(self):
        specs = config.normalize_specs([
            {"site": "A", "evse_ids": ["a"], "valid_from": "2026-11-01", "energy_chf_kwh": 0.38,
             "watch": {"energy_chf_kwh": "migrol:lt22"}},
            {"site": "A", "evse_ids": ["a"], "valid_from": "2026-12-01", "energy_chf_kwh": 0.40,
             "watch": {"energy_chf_kwh": "migrol:lt22"}},           # neuester Eintrag zählt
            {"site": "B", "evse_ids": ["b"], "watch": {"energy_chf_kwh": "iwb:ac.energy"}},
            {"site": "C", "evse_ids": ["c"], "energy_chf_kwh": 0.5, "valid_from": "2026-11-01",
             "watch": {"energy_chf_kwh": "shell:adhoc.le22"}},
        ])
        result = {"migrol": {"values": {"lt22": 0.38}}, "iwb": {"values": {"ac.energy": 0.48}},
                  "shell": {"values": {}, "error": "Seitenstruktur geändert?"}}
        rows = {r["site"]: r for r in pricewatch.compare(specs, result)}
        self.assertEqual(rows["A"]["status"], "abweichung")
        self.assertEqual(rows["A"]["tarife_toml"], 0.40)
        self.assertEqual(rows["B"]["status"], "offen")
        self.assertEqual(rows["C"]["status"], "fehler")


class TarifeTomlTest(unittest.TestCase):
    """Konsistenz der versionierten tarife.toml."""

    @classmethod
    def setUpClass(cls):
        cls.entries = tomllib.loads((ROOT / "tarife.toml").read_text(encoding="utf-8"))["manual_tariff"]
        cls.done, cls.open = config.parse_manual(cls.entries, "tarife.toml")

    def test_all_evse_ids_known(self):
        with (ROOT / "data/discovery/2026-11-06_muttenz.csv").open(encoding="utf-8") as f:
            known = {r["evse_id"] for r in csv.DictReader(f)}
        for e in self.entries:
            for eid in e["evse_ids"]:
                self.assertIn(eid, known, e["site"])

    def test_no_evse_twice_on_same_date(self):
        seen = set()
        for m in self.done:
            for eid in m.evse_ids:
                self.assertNotIn((eid, m.valid_from), seen)
                seen.add((eid, m.valid_from))

    def test_filled_entries_are_documented(self):
        for m in self.done:
            spec = next(e for e in self.entries
                        if [i.upper() for i in e["evse_ids"]] == m.evse_ids and
                        e.get("valid_from") == m.valid_from)
            for field in ("source", "url", "confidence", "note"):
                self.assertTrue(spec.get(field), f"{m.site}: {field} fehlt")
            self.assertIn("verified", spec)

    def test_invalid_confidence(self):
        with self.assertRaises(ValueError):
            config.parse_manual([{"evse_ids": ["X"], "valid_from": "2026-11-01",
                                  "energy_chf_kwh": 1, "confidence": "sicher"}], "t")


if __name__ == "__main__":
    unittest.main()
