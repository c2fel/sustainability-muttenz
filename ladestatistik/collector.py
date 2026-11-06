"""Collector: pollt Status und Tarife und schreibt Status-Intervalle in SQLite.

Abfragen (Standard):
* OCPI ``/status?date_from=…``   alle 60 s  (nur Änderungen, ganze Schweiz, wenige kB)
* OCPI ``/status`` Vollabzug      alle 15 min (Absicherung gegen verpasste Änderungen)
* OICP-Statusdatei                alle 120 s (CPOs ohne OCPI, z.B. MOVE, eCarUp, Migros)
* Katalog (Standorte + Tarife)    alle 6 h  (neue Stationen, Preisänderungen)

Das sind < 2 Requests/Minute – deutlich unter dem Rate-Limit der API.
"""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass

from . import catalog, db, geo, sources
from .config import Config
from .status import normalize

log = logging.getLogger(__name__)

FULL_SNAPSHOT_SINCE = 946684800  # 2000-01-01: liefert den Status aller EVSEs
DELTA_OVERLAP_S = 120


@dataclass
class OpenRun:
    run_id: int
    status_raw: str
    start: int
    end: int
    src_ts: int | None


class Collector:
    def __init__(self, cfg: Config, conn=None):
        self.cfg = cfg
        self.conn = conn or db.connect(cfg.db_path)
        self.scope: dict[str, dict] = {}            # evse_id -> Zeile aus evse
        self.uid_map: dict[tuple, str] = {}         # (cc, party, uid) -> evse_id
        self.open: dict[tuple[str, str], OpenRun] = {}
        self._dirty: set[tuple[str, str]] = set()
        self._last_flush = 0.0
        self._stop = False
        self._load_scope_from_db()
        self._load_open_runs()

    # ------------------------------------------------------------------ Zustand
    def _load_scope_from_db(self) -> None:
        rows = self.conn.execute("SELECT * FROM evse WHERE last_seen = "
                                 "(SELECT MAX(last_seen) FROM evse)").fetchall()
        self._set_scope({r["evse_id"]: dict(r) for r in rows})

    def _set_scope(self, scope: dict[str, dict]) -> None:
        self.scope = scope
        self.uid_map = {(r["ocpi_country"], r["ocpi_party"], r["ocpi_uid"]): eid
                        for eid, r in scope.items() if r.get("in_ocpi")}

    def _load_open_runs(self) -> None:
        rows = self.conn.execute(
            "SELECT r.* FROM status_run r JOIN (SELECT evse_id, source, MAX(id) AS id "
            "FROM status_run GROUP BY evse_id, source) m ON r.id = m.id").fetchall()
        for r in rows:
            self.open[(r["evse_id"], r["source"])] = OpenRun(
                r["id"], r["status_raw"], r["start_ts"], r["end_ts"], r["src_ts"])

    # ---------------------------------------------------------------- Katalog
    def in_scope(self, e: catalog.Evse) -> bool:
        cfg = self.cfg
        if e.evse_id in cfg.exclude_evse_ids:
            return False
        if e.evse_id in cfg.focus_evse_ids:
            return True
        if e.distance_m is not None and e.distance_m <= cfg.record_radius_km * 1000:
            return True
        return cfg.record_municipality and e.in_municipality

    def refresh_catalog(self) -> int:
        cfg = self.cfg
        cat, tmap = catalog.fetch_all(with_oicp=cfg.oicp_enabled)
        try:
            muni = geo.municipality_at(cfg.lat, cfg.lon, cache=cfg.municipality_cache)
            geom = muni.get("geometry")
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemeindegrenze nicht verfügbar: %s", exc)
            geom = None
        catalog.annotate(cat, cfg.lat, cfg.lon, geom)
        now = int(time.time())
        scope: dict[str, dict] = {}
        new_versions = 0
        with self.conn:
            for e in cat.values():
                if not self.in_scope(e):
                    continue
                row = {c: getattr(e, c, None) for c in db.EVSE_COLS if c != "is_focus"}
                row["in_ocpi"] = int(e.in_ocpi)
                row["in_oicp"] = int(e.in_oicp)
                row["in_municipality"] = int(e.in_municipality)
                row["is_focus"] = int(e.evse_id in cfg.focus_evse_ids or
                                      (e.distance_m is not None and
                                       e.distance_m <= cfg.focus_radius_m))
                cols = db.EVSE_COLS
                self.conn.execute(
                    f"INSERT INTO evse ({','.join(cols)}, first_seen, last_seen) "
                    f"VALUES ({','.join('?' * len(cols))}, ?, ?) ON CONFLICT(evse_id) DO UPDATE SET "
                    + ",".join(f"{c}=excluded.{c}" for c in cols[1:]) + ", last_seen=excluded.last_seen",
                    [row[c] for c in cols] + [now, now])
                row["last_seen"] = now
                scope[e.evse_id] = row
                for key in e.tariff_keys:
                    db.upsert_evse_tariff(self.conn, e.evse_id, key, now)
                    if key in tmap and db.upsert_tariff(self.conn, key, tmap[key], now):
                        new_versions += 1
            db.meta_set(self.conn, "catalog_ts", now)
        if not scope:
            raise RuntimeError("Katalog leer – Quellen nicht erreichbar?")
        # last_seen aller Scope-EVSEs ist identisch -> _load_scope_from_db funktioniert
        self._set_scope(scope)
        log.info("Katalog: %d EVSEs im Scope (%d OCPI, %d Fokus), %d neue Tarifversionen",
                 len(scope), len(self.uid_map), sum(r["is_focus"] for r in scope.values()),
                 new_versions)
        return len(scope)

    # ---------------------------------------------------------- Beobachtungen
    def observe(self, evse_id: str, source: str, raw: str, ts: int,
                src_ts: int | None = None) -> None:
        key = (evse_id, source)
        cur = self.open.get(key)
        max_gap = self.cfg.max_gap_s
        if cur and src_ts and cur.src_ts and src_ts < cur.src_ts:
            return  # veralteter Datensatz
        contiguous = cur is not None and ts - cur.end <= max_gap
        if contiguous and cur.status_raw == raw:
            if ts > cur.end:
                cur.end = ts
                self._dirty.add(key)
            if src_ts and not cur.src_ts:
                cur.src_ts = src_ts
            return
        if contiguous:
            # Statuswechsel: exakter Zeitpunkt aus last_updated, sofern plausibel
            change = src_ts if (src_ts and cur.start < src_ts <= ts) else ts
            cur.end = change
            self._flush_one(key)
            start = change
        else:
            start = ts
            if src_ts and src_ts <= ts and ts - src_ts <= max_gap and \
                    (cur is None or src_ts >= cur.end):
                start = src_ts
        status = normalize(raw, source)
        rid = self.conn.execute(
            "INSERT INTO status_run (evse_id, source, status, status_raw, start_ts, end_ts, src_ts)"
            " VALUES (?,?,?,?,?,?,?)", (evse_id, source, status, raw, start, ts, src_ts)).lastrowid
        self.open[key] = OpenRun(rid, raw, start, ts, src_ts)

    def extend(self, source: str, ts: int, evse_ids) -> None:
        """Erfolgreicher Delta-Poll ohne Datensatz = Status unverändert."""
        for eid in evse_ids:
            key = (eid, source)
            cur = self.open.get(key)
            if cur and ts - cur.end <= self.cfg.max_gap_s and ts > cur.end:
                cur.end = ts
                self._dirty.add(key)

    def _flush_one(self, key) -> None:
        cur = self.open[key]
        self.conn.execute("UPDATE status_run SET end_ts=?, src_ts=? WHERE id=?",
                          (cur.end, cur.src_ts, cur.run_id))
        self._dirty.discard(key)

    def flush(self, force: bool = True) -> None:
        """Schreibt verlängerte Intervalle. Neue Intervalle/Statuswechsel werden
        sofort committet; reine Verlängerungen nur alle ``flush_interval_s``
        (schont die SD-Karte des Raspberry Pi)."""
        now = time.time()
        if force or now - self._last_flush >= self.cfg.flush_interval_s:
            for key in list(self._dirty):
                self._flush_one(key)
            self._last_flush = now
        self.conn.commit()

    # ------------------------------------------------------------------ Polls
    def _apply_ocpi(self, records: list[dict], ts: int) -> int:
        n = 0
        for r in records:
            eid = self.uid_map.get((r.get("country_code"), r.get("party_id"),
                                    str(r.get("evse_uid"))))
            if not eid:
                continue
            src = sources.parse_iso(r.get("last_updated"))
            self.observe(eid, "ocpi", r.get("status") or "UNKNOWN", ts,
                         int(src) if src else None)
            n += 1
        return n

    def poll_ocpi_delta(self) -> int:
        now = int(time.time())
        last = int(db.meta_get(self.conn, "ocpi_delta_ok", 0) or 0)
        if now - last > self.cfg.max_gap_s:
            return self.poll_ocpi_full()  # nach Unterbruch: Vollabzug
        recs = sources.fetch_ocpi_status_since(last - DELTA_OVERLAP_S)
        n = self._apply_ocpi(recs, now)
        self.extend("ocpi", now, (eid for eid, r in self.scope.items() if r.get("in_ocpi")))
        db.meta_set(self.conn, "ocpi_delta_ok", now)
        self.flush(force=False)
        return n

    def poll_ocpi_full(self) -> int:
        now = int(time.time())
        recs = sources.fetch_ocpi_status_since(FULL_SNAPSHOT_SINCE)
        n = self._apply_ocpi(recs, now)
        db.meta_set(self.conn, "ocpi_delta_ok", now)
        self.flush(force=False)
        return n

    def poll_oicp(self) -> int:
        now = int(time.time())
        status = sources.fetch_oicp_status()
        n = 0
        for eid, row in self.scope.items():
            if row.get("in_oicp") and eid in status:
                self.observe(eid, "oicp", status[eid], now)
                n += 1
        self.flush(force=False)
        return n

    # --------------------------------------------------------------- Schleife
    def _log_poll(self, kind: str, ok: bool, n: int, ms: int, note: str = "") -> None:
        self.conn.execute("INSERT INTO poll VALUES (?,?,?,?,?,?)",
                          (int(time.time()), kind, int(ok), n, ms, note[:500]))
        self.conn.commit()

    def _run_task(self, kind: str, fn) -> bool:
        t0 = time.time()
        try:
            n = fn()
            self._log_poll(kind, True, n, int((time.time() - t0) * 1000))
            log.debug("%s: %d Datensätze", kind, n)
            return True
        except Exception as exc:  # noqa: BLE001
            self.conn.rollback()
            # In-Memory-Zustand an DB angleichen (zurückgerollte Inserts verwerfen)
            self.open.clear()
            self._dirty.clear()
            self._load_open_runs()
            log.exception("%s fehlgeschlagen", kind)
            self._log_poll(kind, False, 0, int((time.time() - t0) * 1000), repr(exc))
            return False

    def tasks(self):
        cfg = self.cfg
        t = [("catalog", cfg.catalog_interval_s, self.refresh_catalog),
             ("ocpi_full", cfg.ocpi_full_interval_s, self.poll_ocpi_full),
             ("ocpi_delta", cfg.ocpi_delta_interval_s, self.poll_ocpi_delta)]
        if cfg.oicp_enabled:
            t.append(("oicp", cfg.oicp_interval_s, self.poll_oicp))
        return t

    def run_once(self) -> None:
        for kind, _, fn in self.tasks():
            if kind == "ocpi_delta":
                continue  # nach einem Vollabzug überflüssig
            self._run_task(kind, fn)
        self.flush()

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_stop", True))
        catalog_ts = int(db.meta_get(self.conn, "catalog_ts", 0) or 0)
        next_run = {kind: 0.0 for kind, _, _ in self.tasks()}
        if self.scope and time.time() - catalog_ts < self.cfg.catalog_interval_s:
            next_run["catalog"] = catalog_ts + self.cfg.catalog_interval_s
        next_run["ocpi_delta"] = time.time() + self.cfg.ocpi_delta_interval_s
        log.info("Collector gestartet: %d EVSEs im Scope, DB %s", len(self.scope),
                 self.cfg.db_path)
        while not self._stop:
            for kind, interval, fn in self.tasks():
                if self._stop or time.time() < next_run[kind]:
                    continue
                if kind != "catalog" and not self.scope:
                    continue
                ok = self._run_task(kind, fn)
                retry = 300 if kind == "catalog" else min(interval, 60)
                next_run[kind] = time.time() + (interval if ok else retry)
                if kind == "ocpi_full" and ok:
                    next_run["ocpi_delta"] = time.time() + self.cfg.ocpi_delta_interval_s
            wait = max(0.5, min(next_run.values()) - time.time())
            end = time.time() + wait
            while not self._stop and time.time() < end:
                time.sleep(min(1.0, end - time.time()))
        self.flush()
        log.info("Collector beendet")
