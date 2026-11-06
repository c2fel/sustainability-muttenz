"""Auswertung: Auslastung, Ladevorgänge, Tarife und Preis-Auslastungs-Zusammenhang."""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import status as S
from .config import Config
from .tariffs import TZ, price_session, summarize

HOUR = 3600
DAY = 86400


@dataclass
class EvseStats:
    evse_id: str
    source: str = ""
    observed_s: float = 0.0
    operational_s: float = 0.0
    occupied_s: float = 0.0
    out_of_service_s: float = 0.0
    unknown_s: float = 0.0
    sessions: list[tuple[int, int]] = field(default_factory=list)
    occ_how: list[list[float]] = field(default_factory=lambda: [[0.0] * 24 for _ in range(7)])
    op_how: list[list[float]] = field(default_factory=lambda: [[0.0] * 24 for _ in range(7)])
    daily: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0, 0]))

    @property
    def utilization(self) -> float | None:
        return self.occupied_s / self.operational_s if self.operational_s > 0 else None

    @property
    def availability(self) -> float | None:
        """Anteil der beobachteten Zeit, in der der Ladepunkt betriebsbereit war."""
        known = self.operational_s + self.out_of_service_s
        return self.operational_s / known if known > 0 else None


# ------------------------------------------------------------------ Hilfsfunktionen

def _local(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, tz=TZ)


def _split_hours(s: float, e: float):
    """Zerlegt [s, e) an vollen Stunden (CH-Offsets sind ganze Stunden)."""
    while s < e:
        nxt = min(e, (math.floor(s / HOUR) + 1) * HOUR)
        yield s, nxt
        s = nxt


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _ols(xs: list[float], ys: list[float]) -> dict | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return {"n": n, "slope": slope, "intercept": my - slope * mx, "r": sxy / math.sqrt(sxx * syy)}


# ------------------------------------------------------------------ Laden der Daten

def load_runs(conn, start: int, end: int) -> dict[str, dict[str, list]]:
    rows = conn.execute(
        "SELECT evse_id, source, status, start_ts, end_ts FROM status_run "
        "WHERE end_ts > ? AND start_ts < ? ORDER BY evse_id, source, start_ts",
        (start, end)).fetchall()
    out: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        s, e = max(r["start_ts"], start), min(r["end_ts"], end)
        if e > s:
            out[r["evse_id"]][r["source"]].append((s, e, r["status"]))
    return out


def preferred_source(per_source: dict[str, list]) -> str | None:
    """OCPI bevorzugt (präzise Zeitstempel), sonst OICP."""
    for src in ("ocpi", "oicp"):
        if per_source.get(src):
            return src
    return None


def evse_stats(evse_id: str, runs: list[tuple[int, int, str]], cfg: Config,
               source: str) -> EvseStats:
    st = EvseStats(evse_id=evse_id, source=source)
    occ_runs = []
    for s, e, status in runs:
        d = e - s
        st.observed_s += d
        if status in S.OPERATIONAL:
            st.operational_s += d
        elif status == S.OUT_OF_SERVICE:
            st.out_of_service_s += d
        else:
            st.unknown_s += d
        if status == S.OCCUPIED:
            st.occupied_s += d
            occ_runs.append((s, e))
        if status in S.OPERATIONAL:
            for a, b in _split_hours(s, e):
                loc = _local(a)
                st.op_how[loc.weekday()][loc.hour] += b - a
                day = st.daily[loc.date().isoformat()]
                day[1] += b - a
                if status == S.OCCUPIED:
                    st.occ_how[loc.weekday()][loc.hour] += b - a
                    day[0] += b - a
    # Ladevorgänge: belegte Intervalle mit kurzen Unterbrüchen zusammenfassen
    merged: list[list[int]] = []
    for s, e in occ_runs:
        if merged and s - merged[-1][1] <= cfg.merge_gap_s:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    st.sessions = [(s, e) for s, e in merged if e - s >= cfg.min_session_s]
    for s, _ in st.sessions:
        st.daily[_local(s).date().isoformat()][2] += 1
    return st


def group_minutes(runs_by_evse: dict[str, list], start: int, end: int) -> dict:
    """Minutengenaue Gleichzeitigkeit für eine Gruppe (z.B. Nahbereich)."""
    n_min = (end - start) // 60
    if n_min <= 0 or not runs_by_evse:
        return {}
    op = [0] * n_min
    occ = [0] * n_min
    for runs in runs_by_evse.values():
        for s, e, status in runs:
            if status not in S.OPERATIONAL:
                continue
            a, b = max(0, (s - start) // 60), min(n_min, (e - start) // 60)
            for i in range(a, b):
                op[i] += 1
                if status == S.OCCUPIED:
                    occ[i] += 1
    known = [i for i in range(n_min) if op[i] > 0]
    if not known:
        return {}
    full = sum(1 for i in known if occ[i] >= op[i])
    anyocc = sum(1 for i in known if occ[i] > 0)
    full_how = [[0] * 24 for _ in range(7)]
    known_how = [[0] * 24 for _ in range(7)]
    for i in known:
        loc = _local(start + i * 60)
        known_how[loc.weekday()][loc.hour] += 1
        if occ[i] >= op[i]:
            full_how[loc.weekday()][loc.hour] += 1
    return {
        "known_h": round(len(known) / 60, 1),
        "full_share": round(full / len(known), 4),
        "any_occupied_share": round(anyocc / len(known), 4),
        "mean_occupied": round(sum(occ[i] for i in known) / len(known), 3),
        "mean_operational": round(sum(op[i] for i in known) / len(known), 3),
        "full_heatmap": [[round(f / k, 3) if k else None for f, k in zip(fr, kr)]
                         for fr, kr in zip(full_how, known_how)],
    }


# ------------------------------------------------------------------- Tarife

def current_tariffs(conn, cfg: Config) -> dict[str, dict]:
    """EVSE -> aktuell gültiger Tarif (manuell erfasst > API)."""
    out: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT et.evse_id, tv.json FROM evse_tariff et "
        "JOIN (SELECT evse_id, MAX(last_seen) ls FROM evse_tariff GROUP BY evse_id) m "
        "  ON et.evse_id = m.evse_id AND et.last_seen = m.ls "
        "JOIN tariff_version tv ON tv.tariff_key = et.tariff_key "
        "JOIN (SELECT tariff_key, MAX(last_seen) ls FROM tariff_version GROUP BY tariff_key) v "
        "  ON tv.tariff_key = v.tariff_key AND tv.last_seen = v.ls").fetchall()
    for r in rows:
        out.setdefault(r["evse_id"], json.loads(r["json"]))
    out.update(cfg.manual_tariffs)
    return out


def tariff_changes(conn) -> list[dict]:
    """Neue Tarifversionen bzw. Tarifwechsel nach der ersten Erfassung."""
    first = conn.execute("SELECT MIN(first_seen) t FROM tariff_version").fetchone()["t"]
    if first is None:
        return []
    out = []
    for r in conn.execute(
            "SELECT tv.tariff_key, tv.first_seen, tv.json, et.evse_id FROM tariff_version tv "
            "JOIN evse_tariff et ON et.tariff_key = tv.tariff_key "
            "WHERE tv.first_seen > ? + 3600", (first,)):
        out.append({"evse_id": r["evse_id"], "ts": r["first_seen"], "kind": "price",
                    "tariff_key": r["tariff_key"], "tariff": json.loads(r["json"])})
    for r in conn.execute("SELECT evse_id, tariff_key, first_seen FROM evse_tariff "
                          "WHERE first_seen > ? + 3600", (first,)):
        out.append({"evse_id": r["evse_id"], "ts": r["first_seen"], "kind": "tariff_id",
                    "tariff_key": r["tariff_key"]})
    return sorted(out, key=lambda c: c["ts"])


# --------------------------------------------------------------- Hauptauswertung

def _evse_meta(conn) -> dict[str, dict]:
    return {r["evse_id"]: dict(r) for r in conn.execute("SELECT * FROM evse")}


def _ref_prices(tariff: dict | None, power_kw: float | None, cfg: Config) -> dict:
    if not tariff:
        return {}
    return {s.id: price_session(tariff, s, evse_power_kw=power_kw, time_mode=cfg.time_mode)
            for s in cfg.ref_sessions}


def _stats_row(meta: dict, st: EvseStats, tariff: dict | None, cfg: Config,
               days: float, now_status: str | None) -> dict:
    durs = [(e - s) / 60 for s, e in st.sessions]
    obs_days = st.operational_s / DAY if st.operational_s else 0
    return {
        "evse_id": st.evse_id,
        "site_key": meta.get("site_key"),
        "site_name": meta.get("site_name"),
        "address": f"{meta.get('address') or ''}, {meta.get('postal_code') or ''} "
                   f"{meta.get('city') or ''}".strip(", "),
        "operator": meta.get("operator"),
        "distance_m": meta.get("distance_m"),
        "lat": meta.get("lat"), "lon": meta.get("lon"),
        "power_kw": meta.get("power_kw"),
        "power_type": meta.get("power_type"),
        "is_dc": (meta.get("power_type") or "").startswith("DC"),
        "is_focus": bool(meta.get("is_focus")),
        "in_municipality": bool(meta.get("in_municipality")),
        "access": meta.get("access"),
        "opening": meta.get("opening"),
        "source": st.source,
        "status_now": now_status,
        "observed_h": round(st.observed_s / HOUR, 1),
        "operational_h": round(st.operational_s / HOUR, 1),
        "occupied_h": round(st.occupied_s / HOUR, 1),
        "utilization": round(st.utilization, 4) if st.utilization is not None else None,
        "availability": round(st.availability, 4) if st.availability is not None else None,
        "sessions": len(st.sessions),
        "sessions_per_day": round(len(st.sessions) / obs_days, 2) if obs_days >= 0.5 else None,
        "median_session_min": round(statistics.median(durs)) if durs else None,
        "p75_session_min": round(_percentile(durs, 0.75)) if durs else None,
        "share_sessions_over_4h": round(sum(d > 240 for d in durs) / len(durs), 3) if durs else None,
        "tariff": summarize(tariff) if tariff else None,
        "tariff_manual": bool(tariff and tariff.get("_manual_source")),
        "ref_prices": _ref_prices(tariff, meta.get("power_kw"), cfg),
    }


def _price_vs_util(rows: list[dict], ref_id: str, min_operational_h: float) -> dict:
    pts = [r for r in rows if r["utilization"] is not None and r["operational_h"] >= min_operational_h
           and r["ref_prices"].get(ref_id, {}).get("chf_per_kwh")]
    xs = [r["ref_prices"][ref_id]["chf_per_kwh"] for r in pts]
    ys = [r["utilization"] for r in pts]
    res = {"reference_session": ref_id, "n": len(pts), "ols": _ols(xs, ys)}
    pos = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0]
    loglog = _ols([a for a, _ in pos], [b for _, b in pos]) if len(pos) >= 5 else None
    res["elasticity"] = round(loglog["slope"], 3) if loglog else None
    res["elasticity_n"] = len(pos)
    if len(xs) >= 8:
        qs = [_percentile(xs, q) for q in (0.25, 0.5, 0.75)]
        bins = defaultdict(list)
        for x, y in zip(xs, ys):
            bins[sum(x > q for q in qs)].append(y)
        edges = [min(xs)] + qs + [max(xs)]
        res["quartiles"] = [{"from": round(edges[i], 3), "to": round(edges[i + 1], 3),
                             "n": len(bins[i]),
                             "mean_utilization": round(statistics.fmean(bins[i]), 4)
                             if bins[i] else None} for i in range(4)]
    res["points"] = [{"evse_id": r["evse_id"], "x": round(x, 3), "y": round(y, 4),
                      "site_name": r["site_name"], "operator": r["operator"],
                      "is_focus": r["is_focus"], "power_kw": r["power_kw"]}
                     for r, x, y in zip(pts, xs, ys)]
    return res


def _blocking_effect(rows: list[dict]) -> dict:
    """Standzeiten mit vs. ohne Blockier-/Zeitgebühr (nur AC)."""
    groups = {"mit_zeitgebuehr": [], "ohne_zeitgebuehr": []}
    for r in rows:
        if r["is_dc"] or not r["tariff"] or r["median_session_min"] is None:
            continue
        t = r["tariff"]
        has_time = bool(t.get("time_chf_h") or t.get("blocking_chf_h"))
        groups["mit_zeitgebuehr" if has_time else "ohne_zeitgebuehr"].append(r)
    out = {}
    for k, rs in groups.items():
        out[k] = {"n": len(rs),
                  "median_session_min": round(statistics.median(
                      [r["median_session_min"] for r in rs])) if rs else None,
                  "mean_utilization": round(statistics.fmean(
                      [r["utilization"] for r in rs if r["utilization"] is not None]), 4)
                  if any(r["utilization"] is not None for r in rs) else None}
    return out


def _change_effects(changes: list[dict], conn, cfg: Config, window_days: int = 14) -> list[dict]:
    out = []
    for c in changes:
        ts = c["ts"]
        res = {k: v for k, v in c.items() if k != "tariff"}
        res["date"] = _local(ts).date().isoformat()
        if c.get("tariff"):
            res["tariff_after"] = summarize(c["tariff"])["description"]
        for label, a, b in (("before", ts - window_days * DAY, ts), ("after", ts, ts + window_days * DAY)):
            runs = load_runs(conn, a, min(b, int(time.time())))
            src = preferred_source(runs.get(c["evse_id"], {}))
            if src:
                st = evse_stats(c["evse_id"], runs[c["evse_id"]][src], cfg, src)
                res[f"utilization_{label}"] = round(st.utilization, 4) if st.utilization is not None else None
                res[f"operational_h_{label}"] = round(st.operational_s / HOUR, 1)
        out.append(res)
    return out


def _coverage(conn, start: int, end: int, cfg: Config) -> dict:
    out = {}
    for r in conn.execute("SELECT kind, COUNT(*) n, SUM(ok) ok, MAX(CASE WHEN ok THEN ts END) last_ok "
                          "FROM poll WHERE ts >= ? AND ts < ? GROUP BY kind", (start, end)):
        out[r["kind"]] = {"polls": r["n"], "ok_share": round((r["ok"] or 0) / r["n"], 4),
                          "last_ok": r["last_ok"]}
    first = conn.execute("SELECT MIN(start_ts) t FROM status_run").fetchone()["t"]
    out["first_observation"] = first
    return out


def analyze(conn, cfg: Config, days: float = 28, end: int | None = None) -> dict:
    end = int(end or time.time())
    start = int(end - days * DAY)
    first = conn.execute("SELECT MIN(start_ts) t FROM status_run").fetchone()["t"]
    if first and first > start:
        start = int(first)
    runs = load_runs(conn, start, end)
    meta = _evse_meta(conn)
    tariffs = current_tariffs(conn, cfg)
    open_now = {}
    for r in conn.execute("SELECT evse_id, source, status, end_ts FROM status_run "
                          "WHERE end_ts >= ?", (end - cfg.max_gap_s,)):
        if r["source"] == "ocpi" or r["evse_id"] not in open_now:
            open_now[r["evse_id"]] = r["status"]

    rows, stats, chosen_runs = [], {}, {}
    for eid, m in meta.items():
        per_source = runs.get(eid, {})
        src = preferred_source(per_source)
        if not src:
            continue
        st = evse_stats(eid, per_source[src], cfg, src)
        stats[eid] = st
        chosen_runs[eid] = per_source[src]
        rows.append(_stats_row(m, st, tariffs.get(eid), cfg, days, open_now.get(eid)))
    rows.sort(key=lambda r: (r["distance_m"] is None, r["distance_m"] or 0))

    focus_rows = [r for r in rows if r["is_focus"]]
    focus_ids = {r["evse_id"] for r in focus_rows}
    occ = [[0.0] * 24 for _ in range(7)]
    op = [[0.0] * 24 for _ in range(7)]
    for eid in focus_ids:
        for d in range(7):
            for h in range(24):
                occ[d][h] += stats[eid].occ_how[d][h]
                op[d][h] += stats[eid].op_how[d][h]
    heat = [[round(o / p, 3) if p > 0 else None for o, p in zip(orow, prow)]
            for orow, prow in zip(occ, op)]

    sites = defaultdict(list)
    for r in focus_rows:
        sites[r["site_key"]].append(r)
    site_rows = []
    for key, rs in sites.items():
        g = group_minutes({r["evse_id"]: chosen_runs[r["evse_id"]] for r in rs}, start, end)
        g.pop("full_heatmap", None)
        site_rows.append({"site_key": key, "site_name": rs[0]["site_name"],
                          "address": rs[0]["address"], "operator": rs[0]["operator"],
                          "distance_m": rs[0]["distance_m"], "n_evse": len(rs),
                          "sessions_per_day": round(sum(r["sessions_per_day"] or 0 for r in rs), 2),
                          "tariff": rs[0]["tariff"]["description"] if rs[0]["tariff"] else None,
                          **g})
    site_rows.sort(key=lambda s: s["distance_m"] or 0)
    group = group_minutes({eid: chosen_runs[eid] for eid in focus_ids}, start, end)
    fdurs = [(e - s) / 60 for eid in focus_ids for s, e in stats[eid].sessions]
    group_sessions = {
        "sessions": len(fdurs),
        "sessions_per_day": round(sum(r["sessions_per_day"] or 0 for r in focus_rows), 2),
        "median_session_min": round(statistics.median(fdurs)) if fdurs else None,
        "share_over_4h": round(sum(d > 240 for d in fdurs) / len(fdurs), 3) if fdurs else None,
    }

    ids = [s.id for s in cfg.ref_sessions]
    ref = {k: (k if k in ids else ids[0]) for k in ("kurz", "pendler", "schnell")}
    ac = [r for r in rows if not r["is_dc"]]
    dc = [r for r in rows if r["is_dc"]]
    min_h = min(72.0, days * 24 * 0.5)
    daily = []
    for eid, st in stats.items():
        for day, (occ_s, op_s, n) in sorted(st.daily.items()):
            daily.append({"date": day, "evse_id": eid, "occupied_h": round(occ_s / HOUR, 3),
                          "operational_h": round(op_s / HOUR, 3), "sessions": n,
                          "utilization": round(occ_s / op_s, 4) if op_s else None})

    return {
        "generated_at": end,
        "window": {"start": start, "end": end, "days": round((end - start) / DAY, 2)},
        "site": {"name": cfg.site_name, "address": cfg.address, "lat": cfg.lat, "lon": cfg.lon,
                 "focus_radius_m": cfg.focus_radius_m, "record_radius_km": cfg.record_radius_km},
        "reference_sessions": [vars(s) for s in cfg.ref_sessions],
        "coverage": _coverage(conn, start, end, cfg),
        "focus": {"evses": focus_rows, "sites": site_rows, "group": group,
                  "group_sessions": group_sessions, "heatmap": heat},
        "region": {
            "n_evse": len(rows), "n_ac": len(ac), "n_dc": len(dc),
            "n_with_tariff": sum(1 for r in rows if r["tariff"]),
            "ac_price_vs_utilization": _price_vs_util(ac, ref["kurz"], min_h),
            "ac_price_vs_utilization_pendler": _price_vs_util(ac, ref["pendler"], min_h),
            "dc_price_vs_utilization": _price_vs_util(dc, ref["schnell"], min_h),
            "blocking_effect": _blocking_effect(ac),
        },
        "tariff_changes": _change_effects(tariff_changes(conn), conn, cfg),
        "evses": rows,
        "daily": daily,
        "attribution": "Datenquelle: ich-tanke-strom.ch, Bundesamt für Energie BFE "
                       "(https://www.ich-tanke-strom.ch)",
    }
