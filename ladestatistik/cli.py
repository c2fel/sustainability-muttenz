"""Kommandozeile: ``python -m ladestatistik <befehl>``.

Befehle:
  discover   Ladepunkte im Umkreis / in der Gemeinde finden (CSV + Markdown)
  collect    Collector starten (Dauerbetrieb, ``--once`` für einen Durchlauf)
  analyze    Kennzahlen als JSON ausgeben
  publish    Dashboard (HTML) + Daten (JSON/CSV) erzeugen
  health     Zustand der Datenbank / letzte Polls
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

from . import catalog, config, db, geo


def _cfg(args) -> config.Config:
    return config.load(args.config)


def cmd_discover(args) -> int:
    cfg = _cfg(args)
    if args.address:
        cfg.lat, cfg.lon, label = geo.geocode(args.address)
        print(f"Standort: {label} ({cfg.lat:.6f}, {cfg.lon:.6f})", file=sys.stderr)
    cat, tmap = catalog.fetch_all(with_oicp=not args.no_oicp)
    muni = geo.municipality_at(cfg.lat, cfg.lon,
                               cache=None if args.address else cfg.municipality_cache)
    catalog.annotate(cat, cfg.lat, cfg.lon, muni.get("geometry"))
    radius = args.radius
    sel = [e for e in cat.values() if e.distance_m is not None and
           (e.distance_m <= radius or (args.municipality and e.in_municipality))]
    sel.sort(key=lambda e: e.distance_m)
    rows = [catalog.evse_row(e, tmap) for e in sel]
    stamp = dt.date.today().isoformat()
    out = Path(args.out or f"data/discovery/{stamp}_stationen.csv")
    catalog.write_csv(rows, out)
    print(f"{len(rows)} Ladepunkte (≤ {radius:.0f} m"
          f"{' oder Gemeinde ' + str(muni.get('name')) if args.municipality else ''}) -> {out}",
          file=sys.stderr)
    print("| Distanz | EVSE-ID | Standort | Betreiber | Leistung | Status | Tarif (inkl. MWST) |")
    print("|---:|---|---|---|---|---|---|")
    for r in rows:
        status = r["status_ocpi"] or r["status_oicp"]
        print(f"| {r['distance_m']} m | `{r['evse_id']}` | {r['site_name']}, {r['address']} | "
              f"{r['operator']} | {r['power_kw'] or '?'} kW {r['power_type']} | {status} | "
              f"{r['tariff']} |")
    return 0


def cmd_collect(args) -> int:
    from .collector import Collector
    cfg = _cfg(args)
    col = Collector(cfg)
    if args.once:
        col.run_once()
    else:
        col.run_forever()
    return 0


def cmd_analyze(args) -> int:
    from .analyze import analyze
    cfg = _cfg(args)
    res = analyze(db.connect(cfg.db_path), cfg, days=args.days)
    if not args.full:
        res.pop("daily", None)
        res.pop("evses", None)
        for k in ("ac_price_vs_utilization", "ac_price_vs_utilization_pendler",
                  "dc_price_vs_utilization"):
            res["region"][k].pop("points", None)
    json.dump(res, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()
    return 0


def cmd_publish(args) -> int:
    from .publish import publish
    cfg = _cfg(args)
    out = publish(db.connect(cfg.db_path), cfg, days=args.days,
                  out_dir=Path(args.out) if args.out else None)
    print(f"Dashboard geschrieben: {out}")
    return 0


def cmd_health(args) -> int:
    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    now = int(time.time())
    print(f"DB: {cfg.db_path}")
    for r in conn.execute("SELECT COUNT(*) n, SUM(is_focus) f, SUM(in_ocpi) o FROM evse "
                          "WHERE last_seen=(SELECT MAX(last_seen) FROM evse)"):
        print(f"EVSEs im Scope: {r['n']} (Fokus {r['f']}, OCPI {r['o']})")
    r = conn.execute("SELECT COUNT(*) n, MIN(start_ts) a, MAX(end_ts) b FROM status_run").fetchone()
    if r["n"]:
        print(f"Status-Intervalle: {r['n']} von {dt.datetime.fromtimestamp(r['a'])} "
              f"bis {dt.datetime.fromtimestamp(r['b'])}")
    for r in conn.execute("SELECT kind, COUNT(*) n, SUM(ok) ok, MAX(ts) last FROM poll "
                          "WHERE ts > ? GROUP BY kind", (now - 86400,)):
        print(f"  {r['kind']:<11} 24h: {r['ok']}/{r['n']} ok, letzter Poll vor {now - r['last']} s")
    for r in conn.execute("SELECT ts, kind, note FROM poll WHERE ok=0 ORDER BY ts DESC LIMIT 3"):
        print(f"  Fehler {dt.datetime.fromtimestamp(r['ts'])} {r['kind']}: {r['note'][:120]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ladestatistik", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", default=None, help="Pfad zu config.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="Ladepunkte in der Umgebung finden")
    d.add_argument("--radius", type=float, default=1500, help="Radius in Metern (1500)")
    d.add_argument("--municipality", action="store_true", help="ganze Gemeinde einschliessen")
    d.add_argument("--address", help="anderer Standort (Adresse)")
    d.add_argument("--no-oicp", action="store_true", help="nur OCPI-API verwenden")
    d.add_argument("--out", help="CSV-Ausgabedatei")
    d.set_defaults(fn=cmd_discover)

    c = sub.add_parser("collect", help="Status/Tarife aufzeichnen")
    c.add_argument("--once", action="store_true", help="nur ein Durchlauf (Test/Cron)")
    c.set_defaults(fn=cmd_collect)

    a = sub.add_parser("analyze", help="Kennzahlen als JSON")
    a.add_argument("--days", type=float, default=28)
    a.add_argument("--full", action="store_true", help="inkl. aller EVSEs und Tageswerte")
    a.set_defaults(fn=cmd_analyze)

    pb = sub.add_parser("publish", help="Dashboard erzeugen")
    pb.add_argument("--days", type=float, default=28)
    pb.add_argument("--out", help="Ausgabeverzeichnis (Standard: publish.out_dir)")
    pb.set_defaults(fn=cmd_publish)

    h = sub.add_parser("health", help="Zustand der Datenbank")
    h.set_defaults(fn=cmd_health)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
