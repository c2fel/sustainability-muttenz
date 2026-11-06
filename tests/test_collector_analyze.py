import tempfile
import unittest
from pathlib import Path

from ladestatistik import analyze as A
from ladestatistik import db
from ladestatistik.collector import Collector
from ladestatistik.config import Config

T0 = 1_793_000_000  # beliebiger Zeitpunkt


def make_collector(tmp: str) -> Collector:
    cfg = Config(db_path=Path(tmp) / "t.sqlite", cache_dir=Path(tmp))
    return Collector(cfg)


def runs(col, eid="E1", source="ocpi"):
    col.flush()
    return [(r["status_raw"], r["start_ts"] - T0, r["end_ts"] - T0) for r in col.conn.execute(
        "SELECT * FROM status_run WHERE evse_id=? AND source=? ORDER BY id", (eid, source))]


class ObserveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.col = make_collector(self.tmp.name)

    def tearDown(self):
        self.col.conn.close()
        self.tmp.cleanup()

    def test_change_uses_source_timestamp(self):
        c = self.col
        c.observe("E1", "ocpi", "AVAILABLE", T0)
        c.observe("E1", "ocpi", "AVAILABLE", T0 + 60)
        c.observe("E1", "ocpi", "CHARGING", T0 + 120, src_ts=T0 + 90)
        self.assertEqual(runs(c), [("AVAILABLE", 0, 90), ("CHARGING", 90, 120)])

    def test_gap_starts_new_run(self):
        c = self.col
        c.observe("E1", "ocpi", "AVAILABLE", T0)
        c.observe("E1", "ocpi", "AVAILABLE", T0 + 2000)  # > max_gap (600 s)
        self.assertEqual(runs(c), [("AVAILABLE", 0, 0), ("AVAILABLE", 2000, 2000)])

    def test_stale_record_ignored(self):
        c = self.col
        c.observe("E1", "ocpi", "CHARGING", T0 + 60, src_ts=T0 + 50)
        c.observe("E1", "ocpi", "AVAILABLE", T0 + 120, src_ts=T0 + 10)
        self.assertEqual(runs(c), [("CHARGING", 50, 60)])

    def test_extend_without_record(self):
        c = self.col
        c.observe("E1", "ocpi", "CHARGING", T0)
        c.extend("ocpi", T0 + 60, ["E1"])
        c.extend("ocpi", T0 + 120, ["E1"])
        self.assertEqual(runs(c), [("CHARGING", 0, 120)])

    def test_open_runs_survive_restart(self):
        c = self.col
        c.observe("E1", "oicp", "Occupied", T0)
        c.flush()
        c2 = Collector(c.cfg, conn=c.conn)
        c2.observe("E1", "oicp", "Occupied", T0 + 120)
        self.assertEqual(runs(c2, source="oicp"), [("Occupied", 0, 120)])


class AnalyzeTest(unittest.TestCase):
    def test_sessions_and_utilization(self):
        cfg = Config()
        h = 3600
        r = [(T0, T0 + h, "available"),
             (T0 + h, T0 + 2 * h, "occupied"),
             (T0 + 2 * h, T0 + 2 * h + 60, "available"),        # kurzer Unterbruch
             (T0 + 2 * h + 60, T0 + 3 * h, "occupied"),
             (T0 + 3 * h, T0 + 3 * h + 120, "occupied"),         # < min_session? Teil davon
             (T0 + 3 * h + 120, T0 + 4 * h, "out_of_service")]
        st = A.evse_stats("E1", r, cfg, "ocpi")
        self.assertAlmostEqual(st.utilization, (2 * h + 60) / (3 * h + 120), places=4)
        self.assertEqual(len(st.sessions), 1)  # zusammengeführt
        self.assertEqual(st.sessions[0], (T0 + h, T0 + 3 * h + 120))
        self.assertAlmostEqual(st.availability, (3 * h + 120) / (4 * h), places=4)

    def test_group_full_share(self):
        h = 3600
        g = A.group_minutes({
            "A": [(T0, T0 + 2 * h, "occupied")],
            "B": [(T0, T0 + h, "occupied"), (T0 + h, T0 + 2 * h, "available")],
        }, T0, T0 + 2 * h)
        self.assertAlmostEqual(g["full_share"], 0.5, places=3)
        self.assertAlmostEqual(g["any_occupied_share"], 1.0, places=3)
        self.assertAlmostEqual(g["mean_occupied"], 1.5, places=3)

    def test_end_to_end_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = make_collector(tmp)
            col.conn.execute("INSERT INTO evse (evse_id, site_key, site_name, distance_m, "
                             "power_kw, power_type, is_focus, last_seen) "
                             "VALUES ('E1','s1','Test',100,22,'AC_3_PHASE',1,1)")
            col.observe("E1", "ocpi", "AVAILABLE", T0)
            col.observe("E1", "ocpi", "CHARGING", T0 + 600, src_ts=T0 + 600)
            col.extend("ocpi", T0 + 1200, ["E1"])  # Delta-Poll ohne Änderung
            col.observe("E1", "ocpi", "AVAILABLE", T0 + 1800, src_ts=T0 + 1800)
            col.observe("E1", "ocpi", "AVAILABLE", T0 + 2400)
            col.flush()
            res = A.analyze(col.conn, col.cfg, days=1, end=T0 + 2400)
            e = res["focus"]["evses"][0]
            self.assertEqual(e["sessions"], 1)
            self.assertEqual(e["median_session_min"], 20)
            self.assertAlmostEqual(e["utilization"], 0.5, places=3)
            col.conn.close()


if __name__ == "__main__":
    unittest.main()
