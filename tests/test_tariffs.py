import json
import unittest
from pathlib import Path

from ladestatistik import tariffs as T

FIX = {f"{t['country_code']}*{t['party_id']}*{t['id']}": t for t in json.loads(
    (Path(__file__).parent / "fixtures" / "tariffs_2026-11-06.json").read_text())}
REF = {s.id: s for s in T.DEFAULT_REF_SESSIONS}


class PriceSessionTest(unittest.TestCase):
    def test_swisscharge_energy_plus_time(self):
        # Hardstrasse 21: 0.36 CHF/kWh + 1.11 CHF/h exkl. 8.1 % MWST
        r = T.price_session(FIX["CH*SUI*4335"], REF["kurz"], evse_power_kw=22)
        self.assertAlmostEqual(r["breakdown"]["ENERGY"], 10 * 0.36 * 1.081, places=2)
        self.assertAlmostEqual(r["breakdown"]["TIME"], 1.11 * 1.081, places=2)
        self.assertEqual(r["total_chf"], 5.09)

    def test_energie360_blocking_after_4h_daytime_only(self):
        t = FIX["CH*360*1459"]
        # Di 07:00, 9 h: 07–11 gratis (4 h), 11–16 Uhr Blockiergebühr 4.44 CHF/h netto
        r = T.price_session(t, REF["pendler"], evse_power_kw=22)
        self.assertAlmostEqual(r["breakdown"]["TIME"], 5 * 4.44 * 1.081, places=2)
        self.assertAlmostEqual(r["breakdown"]["ENERGY"], 25 * 0.5 * 1.081, places=2)
        # Mi 19:00, 12 h: nach 23 Uhr ausserhalb 08–20 -> keine Zeitgebühr
        r = T.price_session(t, REF["nacht"], evse_power_kw=22)
        self.assertEqual(r["breakdown"].get("TIME", 0), 0)

    def test_time_only_tariff_with_day_night(self):
        t = FIX["CH*IWB*997"]  # 4.44 CHF/h 06–22, sonst 2.78 CHF/h, keine Energiekosten
        r = T.price_session(t, REF["kurz"], evse_power_kw=22)
        self.assertAlmostEqual(r["total_chf"], 4.44 * 1.081, places=2)
        r = T.price_session(t, REF["nacht"], evse_power_kw=22)  # 19–22 + 06–07 Tag, sonst Nacht
        self.assertAlmostEqual(r["total_chf"], (4 * 4.44 + 8 * 2.78) * 1.081, places=1)

    def test_step_size_rounds_up(self):
        t = {"tax_included": "YES", "elements": [{"price_components": [
            {"type": "TIME", "price": 6.0, "step_size": 900}]}]}  # 15-min-Schritte
        s = T.RefSession("x", "x", 0, "10:00", 20, 1, 11)
        self.assertEqual(T.price_session(t, s)["total_chf"], 3.0)  # 20 min -> 30 min

    def test_parking_time_only_after_charging(self):
        t = {"tax_included": "YES", "elements": [{"price_components": [
            {"type": "ENERGY", "price": 0.5, "step_size": 1},
            {"type": "PARKING_TIME", "price": 2.0, "step_size": 60}]}]}
        s = T.RefSession("x", "x", 0, "10:00", 120, 11, 11)  # 1 h laden, 1 h parkieren
        r = T.price_session(t, s)
        self.assertAlmostEqual(r["breakdown"]["PARKING_TIME"], 2.0, places=2)
        self.assertAlmostEqual(r["breakdown"]["ENERGY"], 5.5, places=2)

    def test_time_mode_charging(self):
        t = {"tax_included": "YES", "elements": [{"price_components": [
            {"type": "TIME", "price": 1.0, "step_size": 60}]}]}
        s = T.RefSession("x", "x", 0, "10:00", 180, 11, 11)  # 1 h laden, 2 h stehen
        self.assertEqual(T.price_session(t, s, time_mode="session")["total_chf"], 3.0)
        self.assertEqual(T.price_session(t, s, time_mode="charging")["total_chf"], 1.0)

    def test_from_simple_blocking(self):
        t = T.from_simple({"energy_chf_kwh": 0.5, "time_chf_h": 1.0, "blocking_chf_h": 5.0,
                           "blocking_after_min": 120})
        s = T.RefSession("x", "x", 0, "10:00", 180, 10, 11)
        r = T.price_session(t, s)
        self.assertAlmostEqual(r["total_chf"], 5.0 + 2 * 1.0 + 1 * 5.0, places=2)
        summ = T.summarize(t)
        self.assertEqual(summ["blocking_chf_h"], 5.0)
        self.assertEqual(summ["blocking_after_min"], 120)


class RestrictionTest(unittest.TestCase):
    def test_time_window_over_midnight(self):
        self.assertTrue(T._hm_in("23:30", "22:00", "06:00"))
        self.assertTrue(T._hm_in("05:59", "22:00", "06:00"))
        self.assertFalse(T._hm_in("06:00", "22:00", "06:00"))
        self.assertFalse(T._hm_in("12:00", "22:00", "06:00"))


class DescribeTest(unittest.TestCase):
    def test_summary_energie360(self):
        s = T.summarize(FIX["CH*360*1459"])
        self.assertAlmostEqual(s["energy_chf_kwh"], 0.5405, places=3)
        self.assertEqual(s["blocking_after_min"], 240)
        self.assertIn("bis 4 h", s["description"])

    def test_missing(self):
        self.assertEqual(T.describe(None), "Tarif nicht in der API")


if __name__ == "__main__":
    unittest.main()
