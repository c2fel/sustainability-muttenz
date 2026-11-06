"""Kommandozeile: ``python -m ladestatistik <befehl>``.

Befehle:
  discover         Ladepunkte in der Gemeinde (und optional im Umkreis) finden
  collect          Collector starten (Dauerbetrieb, ``--once`` für einen Durchlauf)
  analyze          Kennzahlen als JSON ausgeben
  publish          Web-Root erzeugen (Übersicht + reports/charging/ mit Dashboard und Daten)
  serve            Web-Root lokal ausliefern (für den Cloudflare-Tunnel)
  tariff-template  Vorlage für manuelle Tarife (tarife.toml) erzeugen/ergänzen
  tariff-check     Preisseiten der Betreiber abrufen und mit tarife.toml vergleichen
  health           Zustand der Datenbank, letzte Polls, Tarifabdeckung
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import tempfile
import time
from pathlib import Path

from . import catalog, config, db, geo


def _cfg(args) -> config.Config:
    return config.load(args.config)


def cmd_discover(args) -> int:
    cfg = _cfg(args)
    if args.address:
        cfg.lat, cfg.lon, label = geo.geocode(args.address)
        cfg.cache_dir = Path(tempfile.mkdtemp())  # anderer Standort: Gemeinde-Cache nicht nutzen
        print(f"Standort: {label} ({cfg.lat:.6f}, {cfg.lon:.6f})", file=sys.stderr)
    cfg.record_radius_km = args.radius / 1000
    cfg.record_municipality = not args.no_municipality
    cat, tmap = catalog.fetch_all(with_oicp=not args.no_oicp)
    muni = catalog.annotate_municipality(cat, cfg)
    sel = sorted((e for e in cat.values() if catalog.in_scope(e, cfg)),
                 key=lambda e: (e.distance_m is None, e.distance_m or 0, e.evse_id))
    rows = [catalog.evse_row(e, tmap) for e in sel]
    stamp = dt.date.today().isoformat()
    out = Path(args.out or f"data/discovery/{stamp}_stationen.csv")
    catalog.write_csv(rows, out)
    scope = [f"Gemeinde {muni}"] if cfg.record_municipality else []
    if args.radius:
        scope.append(f"Umkreis {args.radius:.0f} m")
    print(f"{len(rows)} Ladepunkte ({' + '.join(scope)}) -> {out}", file=sys.stderr)
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
            res["municipality"][k].pop("points", None)
        res["focus"].pop("timeline", None)
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


def cmd_serve(args) -> int:
    from .serve import serve
    cfg = _cfg(args)
    serve(cfg.out_dir, host=args.host, port=args.port)
    return 0


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


TEMPLATE_HEADER = """\
# Manuell erfasste Tarife (Bruttopreise in CHF inkl. MWST, wie in App/Display angezeigt)
#
# - Ein [[manual_tariff]]-Eintrag gilt ab valid_from (Datum, an dem der Preis gilt bzw.
#   geprüft wurde) für alle evse_ids des Eintrags.
# - Preisänderung: Eintrag kopieren, neues valid_from und neue Preise eintragen, den alten
#   Eintrag stehen lassen. So entsteht der Preisverlauf für die Vorher/Nachher-Auswertung.
# - Einträge ohne valid_from oder ohne Preisfeld gelten als "offen" und werden ignoriert.
# - Ein manueller Tarif hat Vorrang vor einem Tarif aus der BFE-API.
#
# Felder (alle optional ausser valid_from + mindestens ein Preis):
#   energy_chf_kwh      Preis pro kWh
#   time_chf_h          Zeitpreis pro Stunde ab Minute 0 (Anschlussdauer)
#   blocking_chf_h      Zeitpreis pro Stunde ab blocking_after_min (ersetzt time_chf_h)
#   blocking_after_min  Minuten ohne Blockiergebühr
#   blocking_start/_end Blockiergebühr nur in diesem Zeitfenster, z.B. "08:00"/"20:00"
#   flat_chf            Start-/Sessionsgebühr pro Ladevorgang
#   source              Quelle, z.B. "IWB-App, Screenshot 2026-11-10"
#
# Neue Stationen ergänzen:
#   python -m ladestatistik -c config.toml tariff-template --out tarife.toml
"""


def cmd_tariff_template(args) -> int:
    from collections import defaultdict
    from .tariffs import summarize
    cfg = _cfg(args)
    cat, tmap = catalog.fetch_all(with_oicp=cfg.oicp_enabled)
    catalog.annotate_municipality(cat, cfg)
    known = {eid for m in cfg.manual_tariffs for eid in m.evse_ids} | \
            {eid for o in cfg.manual_open for eid in o["evse_ids"]}
    out_path = Path(args.out) if args.out else None
    if out_path and out_path.exists():
        import tomllib
        for spec in tomllib.loads(out_path.read_text(encoding="utf-8")).get("manual_tariff", []):
            known |= {e.upper() for e in spec.get("evse_ids", [])}
    sites: dict[tuple, list] = defaultdict(list)   # AC und DC getrennt (andere Preise)
    for e in cat.values():
        if catalog.in_scope(e, cfg):
            sites[(e.site_key, e.is_dc)].append(e)
    blocks = []
    for evses in sorted(sites.values(), key=lambda es: min(e.distance_m or 0 for e in es)):
        evses.sort(key=lambda e: e.evse_id)
        api = [summarize(tmap[k])["description"] for e in evses for k in e.tariff_keys if k in tmap]
        if any(e.evse_id in known for e in evses) or (api and not args.all):
            continue
        e0 = evses[0]
        kinds = ", ".join(sorted({f"{e.power_kw or '?':g} kW {'DC' if e.is_dc else 'AC'}"
                                  if e.power_kw else "? kW" for e in evses}))
        label = f"{e0.site_name}, {e0.address} ({e0.distance_m} m)" + (" – DC" if e0.is_dc else "")
        lines = [
            "[[manual_tariff]]",
            f"site = {_toml_str(label)}",
            f"evse_ids = [{', '.join(_toml_str(e.evse_id) for e in evses)}]",
            f"# {len(evses)} Ladepunkt(e), {kinds} · {e0.operator}"
            + (f" · Zugang: {catalog.access_de(e0.access)}" if e0.access else ""),
        ]
        if api:
            lines.append(f"# Tarif laut BFE-API: {api[0]}")
        lines += ['# valid_from = "2026-11-__"', '# source = ""', "# energy_chf_kwh = ",
                  "# time_chf_h = ", "# blocking_chf_h = ", "# blocking_after_min = ",
                  "# flat_chf = "]
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks) + ("\n" if blocks else "")
    if not out_path:
        print(TEMPLATE_HEADER + "\n" + text)
    elif not blocks:
        print(f"{out_path}: keine neuen Standorte ohne Tarif", file=sys.stderr)
    else:
        prefix = "" if out_path.exists() else TEMPLATE_HEADER + "\n"
        with out_path.open("a", encoding="utf-8") as f:
            f.write(prefix + ("\n" if not prefix else "") + text)
        print(f"{out_path}: {len(blocks)} Standorte ergänzt", file=sys.stderr)
    return 0


def cmd_tariff_check(args) -> int:
    from . import pricewatch
    cfg = _cfg(args)
    result = pricewatch.fetch_all()
    snap = pricewatch.save_snapshot(result, cfg.cache_dir.parent / "pricewatch")
    print(f"Snapshot: {snap}")
    for sid, r in result.items():
        state = f"FEHLER: {r['error']}" if r.get("error") else f"{len(r.get('values') or {})} Werte"
        print(f"  {sid:<11} {state}  ({r['url']})")
    rows = pricewatch.compare(cfg.manual_specs, result)
    if not rows:
        print("Keine Einträge mit 'watch' in der Tarifdatei.")
        return 0
    print()
    print(f"{'Status':<11} {'Feld':<19} {'tarife.toml':>11} {'Website':>8}  Standort")
    for r in sorted(rows, key=lambda r: (r["status"] == "ok", r["site"])):
        fmt = lambda v: "–" if v is None else f"{float(v):g}"
        print(f"{r['status']:<11} {r['field']:<19} {fmt(r['tarife_toml']):>11} {fmt(r['website']):>8}  "
              f"{r['site'][:60]}")
    bad = [r for r in rows if r["status"] in ("abweichung", "fehler")]
    if bad:
        print(f"\n{len(bad)} Abweichung(en)/Fehler: Preis prüfen und in tarife.toml einen neuen "
              f"Eintrag mit neuem valid_from erfassen (den alten stehen lassen).")
    return 1 if bad else 0


def cmd_health(args) -> int:
    from .analyze import api_tariff_evses, current_tariffs
    cfg = _cfg(args)
    conn = db.connect(cfg.db_path)
    now = int(time.time())
    print(f"DB: {cfg.db_path}")
    scope = [r["evse_id"] for r in conn.execute(
        "SELECT evse_id FROM evse WHERE last_seen=(SELECT MAX(last_seen) FROM evse)")]
    focus = conn.execute("SELECT COUNT(*) n FROM evse WHERE is_focus=1 AND "
                         "last_seen=(SELECT MAX(last_seen) FROM evse)").fetchone()["n"]
    print(f"Ladepunkte im Scope: {len(scope)} (Nahbereich {focus})")
    r = conn.execute("SELECT COUNT(*) n, MIN(start_ts) a, MAX(end_ts) b FROM status_run").fetchone()
    if r["n"]:
        print(f"Status-Intervalle: {r['n']} von {dt.datetime.fromtimestamp(r['a'])} "
              f"bis {dt.datetime.fromtimestamp(r['b'])}")
    for r in conn.execute("SELECT kind, COUNT(*) n, SUM(ok) ok, MAX(ts) last FROM poll "
                          "WHERE ts > ? GROUP BY kind", (now - 86400,)):
        print(f"  {r['kind']:<11} 24h: {r['ok']}/{r['n']} ok, letzter Poll vor {now - r['last']} s")
    for r in conn.execute("SELECT ts, kind, note FROM poll WHERE ok=0 ORDER BY ts DESC LIMIT 3"):
        print(f"  Fehler {dt.datetime.fromtimestamp(r['ts'])} {r['kind']}: {r['note'][:120]}")
    tariffs = current_tariffs(conn, cfg)
    api_ids = api_tariff_evses(conn)
    origin = [tariffs.get(eid, {}).get("_origin") for eid in scope]
    print(f"Tarife: {origin.count('api')} aus API, {origin.count('manual')} manuell, "
          f"{origin.count(None)} fehlen"
          + (f" (Datei {cfg.manual_file.name}: {len(cfg.manual_open)} Einträge offen)"
             if cfg.manual_file else ""))
    missing = sorted(eid for eid in scope if eid not in tariffs)
    if missing:
        print("  ohne Tarif: " + ", ".join(missing))
    unverified = sorted({m.site or m.evse_ids[0] for m in cfg.manual_tariffs if not m.verified})
    if unverified:
        print(f"  {len(unverified)} manuelle Einträge noch nicht geprüft (verified = false)")
    overrides = sorted(eid for eid in scope
                       if tariffs.get(eid, {}).get("_origin") == "manual" and eid in api_ids)
    if overrides:
        print("  manuell, obwohl API-Tarif vorhanden (prüfen): " + ", ".join(overrides))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ladestatistik", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", default=None, help="Pfad zu config.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="Ladepunkte in der Gemeinde finden")
    d.add_argument("--radius", type=float, default=0,
                   help="zusätzlich Umkreis in Metern (Standard 0 = nur Gemeinde)")
    d.add_argument("--no-municipality", action="store_true", help="nur Umkreis, ohne Gemeinde")
    d.add_argument("--address", help="anderer Standort (Adresse)")
    d.add_argument("--no-oicp", action="store_true", help="nur OCPI-API verwenden")
    d.add_argument("--out", help="CSV-Ausgabedatei")
    d.set_defaults(fn=cmd_discover)

    c = sub.add_parser("collect", help="Status/Tarife aufzeichnen")
    c.add_argument("--once", action="store_true", help="nur ein Durchlauf (Test/Cron)")
    c.set_defaults(fn=cmd_collect)

    a = sub.add_parser("analyze", help="Kennzahlen als JSON")
    a.add_argument("--days", type=float, default=28)
    a.add_argument("--full", action="store_true", help="inkl. aller Ladepunkte und Tageswerte")
    a.set_defaults(fn=cmd_analyze)

    pb = sub.add_parser("publish", help="Web-Root mit Dashboard erzeugen")
    pb.add_argument("--days", type=float, default=28)
    pb.add_argument("--out", help="Web-Root (Standard: publish.out_dir)")
    pb.set_defaults(fn=cmd_publish)

    sv = sub.add_parser("serve", help="Web-Root ausliefern")
    sv.add_argument("--host", default="127.0.0.1", help="127.0.0.1 (Standard) oder 0.0.0.0")
    sv.add_argument("--port", type=int, default=8099)
    sv.set_defaults(fn=cmd_serve)

    t = sub.add_parser("tariff-template", help="Vorlage für manuelle Tarife")
    t.add_argument("--out", help="Datei ergänzen (z.B. tarife.toml) statt Ausgabe auf stdout")
    t.add_argument("--all", action="store_true", help="auch Standorte mit API-Tarif")
    t.set_defaults(fn=cmd_tariff_template)

    tc = sub.add_parser("tariff-check", help="Preisseiten abrufen und mit tarife.toml vergleichen")
    tc.set_defaults(fn=cmd_tariff_check)

    h = sub.add_parser("health", help="Zustand der Datenbank")
    h.set_defaults(fn=cmd_health)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
