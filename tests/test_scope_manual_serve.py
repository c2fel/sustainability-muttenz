import datetime as dt
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ladestatistik import analyze as A
from ladestatistik import catalog, config
from ladestatistik.collector import Collector
from ladestatistik.config import Config
from ladestatistik.serve import make_server

ENTRIES = [
    {"site": "IWB", "evse_ids": ["ch*iwb*e1", "CH*IWB*E2"], "valid_from": "2026-11-01",
     "energy_chf_kwh": 0.50},
    {"site": "IWB", "evse_ids": ["CH*IWB*E1", "CH*IWB*E2"], "valid_from": "2026-12-01",
     "energy_chf_kwh": 0.60, "blocking_chf_h": 3.0, "blocking_after_min": 240},
    {"site": "Coop", "evse_ids": ["CH*360*E9"]},                       # offen: kein Preis
    {"site": "Migros", "evse_ids": ["CH*MIG*E5"], "energy_chf_kwh": 0.4},  # offen: kein Datum
]


class ManualTariffTest(unittest.TestCase):
    def test_parse_open_and_done(self):
        done, open_ = config.parse_manual(ENTRIES, "test")
        self.assertEqual(len(done), 2)
        self.assertEqual([o["site"] for o in open_], ["Coop", "Migros"])
        self.assertEqual(done[0].evse_ids, ["CH*IWB*E1", "CH*IWB*E2"])  # normalisiert

    def test_invalid_date(self):
        with self.assertRaises(ValueError):
            config.parse_manual([{"evse_ids": ["X"], "valid_from": "1.11.2026",
                                  "energy_chf_kwh": 1}], "test")

    def test_valid_from_selection(self):
        cfg = Config()
        cfg.manual_tariffs, _ = config.parse_manual(ENTRIES, "test")
        self.assertIsNone(cfg.manual_tariff_for("CH*IWB*E1", dt.date(2026, 10, 31)))
        self.assertEqual(cfg.manual_tariff_for("CH*IWB*E1", dt.date(2026, 11, 15)).valid_from,
                         "2026-11-01")
        self.assertEqual(cfg.manual_tariff_for("CH*IWB*E1", dt.date(2026, 12, 1)).valid_from,
                         "2026-12-01")

    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "tarife.toml").write_text(
                '[[manual_tariff]]\nevse_ids = ["CH*IWB*E1"]\nvalid_from = "2026-11-01"\n'
                'energy_chf_kwh = 0.5\n\n[[manual_tariff]]\nevse_ids = ["CH*X*E1"]\n'
                '# valid_from = "2026-11-__"\n', encoding="utf-8")
            Path(tmp, "config.toml").write_text('[tariffs]\nmanual_file = "tarife.toml"\n'
                                                '[publish]\nreport_path = "/reports/charging/"\n',
                                                encoding="utf-8")
            cfg = config.load(Path(tmp, "config.toml"))
            self.assertEqual(len(cfg.manual_tariffs), 1)
            self.assertEqual(len(cfg.manual_open), 1)
            self.assertEqual(cfg.report_path, "reports/charging")
            self.assertEqual(cfg.report_url, "https://stats.jumut.ch/reports/charging/")

    def test_current_tariffs_and_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(db_path=Path(tmp) / "t.sqlite", cache_dir=Path(tmp))
            cfg.manual_tariffs, _ = config.parse_manual(ENTRIES, "test")
            col = Collector(cfg)
            nov = int(dt.datetime(2026, 11, 15, 12, tzinfo=A.TZ).timestamp())
            t = A.current_tariffs(col.conn, cfg, at=nov)
            self.assertEqual(t["CH*IWB*E1"]["_origin"], "manual")
            self.assertEqual(t["CH*IWB*E1"]["elements"][-1]["price_components"][0]["price"], 0.5)
            changes = A.tariff_changes(col.conn, cfg)
            self.assertEqual({c["evse_id"] for c in changes}, {"CH*IWB*E1", "CH*IWB*E2"})
            self.assertEqual(A._local(changes[0]["ts"]).date().isoformat(), "2026-12-01")
            col.conn.close()


class ScopeTest(unittest.TestCase):
    def evse(self, **kw):
        return catalog.Evse(evse_id=kw.pop("evse_id", "E"), **kw)

    def test_municipality_only(self):
        cfg = Config()  # Standard: nur Gemeinde, kein Umkreis
        self.assertTrue(catalog.in_scope(self.evse(distance_m=1900, in_municipality=True), cfg))
        self.assertFalse(catalog.in_scope(self.evse(distance_m=300, in_municipality=False), cfg))

    def test_focus_and_exclude(self):
        cfg = Config(focus_evse_ids=["F"], exclude_evse_ids=["X"])
        self.assertTrue(catalog.in_scope(self.evse(evse_id="F", distance_m=5000), cfg))
        self.assertFalse(catalog.in_scope(self.evse(evse_id="X", in_municipality=True), cfg))
        self.assertTrue(catalog.is_focus(self.evse(distance_m=799), cfg))
        self.assertFalse(catalog.is_focus(self.evse(distance_m=801), cfg))

    def test_optional_radius(self):
        cfg = Config(record_radius_km=2)
        self.assertTrue(catalog.in_scope(self.evse(distance_m=1500), cfg))

    def test_analysis_ignores_evses_outside_current_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = Collector(Config(db_path=Path(tmp) / "t.sqlite", cache_dir=Path(tmp)))
            col.conn.execute("INSERT INTO evse (evse_id, last_seen) VALUES ('alt', 1), ('neu', 2)")
            self.assertEqual(set(A._evse_meta(col.conn)), {"neu"})
            col.conn.close()


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "reports" / "charging" / "data").mkdir(parents=True)
        (root / "index.html").write_text("<p>root</p>")
        (root / "reports" / "charging" / "index.html").write_text("<p>report</p>")
        (root / "reports" / "charging" / "data" / "daily.csv").write_text("a,b\n1,2\n")
        cls.httpd = make_server(root, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            r = opener.open(self.base + path, timeout=5)
            return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, b""

    def test_report_and_cache_headers(self):
        code, h, body = self.get("/reports/charging/")
        self.assertEqual((code, body), (200, b"<p>report</p>"))
        self.assertEqual(h["Cache-Control"], "no-cache")
        code, h, _ = self.get("/reports/charging/data/daily.csv")
        self.assertEqual(code, 200)
        self.assertEqual(h["Cache-Control"], "public, max-age=300")
        self.assertTrue(h["Content-Type"].startswith("text/csv"))
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_no_directory_listing_and_api_404(self):
        for path in ("/reports/charging/data/", "/api/v1/stations"):
            code, h, _ = self.get(path)
            self.assertEqual(code, 404, path)
            self.assertEqual(h["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
