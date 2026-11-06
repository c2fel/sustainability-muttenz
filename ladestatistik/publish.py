"""Erzeugt den Web-Root für stats.jumut.ch.

Struktur (Standard ``out_dir = site``, ``report_path = reports/charging``)::

  site/
    index.html                     Übersicht aller Reports
    robots.txt
    reports/index.html             (gleiche Übersicht)
    reports/charging/index.html    Dashboard (Daten eingebettet)
    reports/charging/data/summary.json   Kennzahlen (ohne Tageswerte)
    reports/charging/data/daily.csv      Tageswerte pro Ladepunkt
    reports/charging/data/evses.csv      alle Ladepunkte mit Kennzahlen und Tarif
"""

from __future__ import annotations

import csv
import html as htmllib
import json
import os
import subprocess
import time
from importlib import resources
from pathlib import Path

from .analyze import analyze
from .config import Config


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _evse_csv_rows(rows: list[dict], ref_ids: list[str]):
    for r in rows:
        t = r.get("tariff") or {}
        out = {k: r.get(k) for k in (
            "evse_id", "site_name", "address", "operator", "owner", "distance_m", "lat", "lon",
            "power_kw", "power_type", "is_focus", "access", "opening", "ocpi_id", "source",
            "status_now", "observed_h", "operational_h", "occupied_h", "utilization",
            "availability", "sessions", "sessions_per_day", "median_session_min",
            "p75_session_min", "share_sessions_over_4h")}
        out.update({"tariff": t.get("description"), "tariff_origin": r.get("tariff_origin"),
                    "tariff_source": r.get("tariff_source"),
                    "energy_chf_kwh": t.get("energy_chf_kwh"), "time_chf_h": t.get("time_chf_h"),
                    "blocking_chf_h": t.get("blocking_chf_h"),
                    "blocking_after_min": t.get("blocking_after_min"),
                    "flat_chf": t.get("flat_chf")})
        for rid in ref_ids:
            p = r.get("ref_prices", {}).get(rid) or {}
            out[f"chf_{rid}"] = p.get("total_chf")
            out[f"chf_per_kwh_{rid}"] = p.get("chf_per_kwh")
        yield out


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    os.replace(tmp, path)


def code_version() -> dict:
    """Ausgerollter Git-Stand (für Footer und /version.json), falls verfügbar."""
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h|%cI|%s"],
                             capture_output=True, text=True, timeout=5)
        commit, date, subject = out.stdout.strip().split("|", 2)
        return {"commit": commit, "date": date, "subject": subject}
    except Exception:  # noqa: BLE001 - kein Git (z.B. Paket-Installation)
        return {}


def _landing(cfg: Config, report_href: str) -> str:
    noindex = "" if cfg.allow_indexing else '<meta name="robots" content="noindex">\n'
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{noindex}<title>Statistiken jumut</title>
<style>
:root {{ color-scheme: light; --page:#f9f9f7; --surface:#fcfcfb; --ring:rgba(11,11,11,.10);
  --text:#0b0b0b; --muted:#52514e; --link:#2a78d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ring:rgba(255,255,255,.10); --text:#f0efec; --muted:#c3c2b7; --link:#3987e5; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19;
  --ring:rgba(255,255,255,.10); --text:#f0efec; --muted:#c3c2b7; --link:#3987e5; }}
body {{ margin:0; background:var(--page); color:var(--text);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:720px; margin:0 auto; padding:40px 16px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} p {{ color:var(--muted); margin:0 0 24px; }}
a.card {{ display:block; background:var(--surface); box-shadow:0 0 0 1px var(--ring);
  border-radius:12px; padding:16px 18px; color:inherit; text-decoration:none; }}
a.card:hover, a.card:focus-visible {{ box-shadow:0 0 0 2px var(--link); }}
a.card b {{ color:var(--link); }} a.card span {{ display:block; color:var(--muted); font-size:14px; }}
</style>
</head>
<body><main>
<h1>Statistiken</h1>
<p>Auswertungen rund um Energie und Mobilität am Standort {htmllib.escape(cfg.address)}.</p>
<a class="card" href="{report_href}"><b>{htmllib.escape(cfg.public_title)}</b>
<span>Belegung und Tarife der öffentlichen Ladestationen in {htmllib.escape(cfg.municipality)}</span></a>
</main></body></html>
"""


def publish(conn, cfg: Config, days: float = 28, out_dir: Path | None = None) -> Path:
    root = Path(out_dir or cfg.out_dir)
    report = root / cfg.report_path
    res = analyze(conn, cfg, days=days)
    res["title"] = cfg.public_title
    res["version"] = code_version()

    daily = res.pop("daily")
    evses = res.pop("evses")
    ref_ids = [s.id for s in cfg.ref_sessions]
    _write_csv(report / "data" / "daily.csv", daily)
    _write_csv(report / "data" / "evses.csv", list(_evse_csv_rows(evses, ref_ids)))
    _atomic_write(report / "data" / "summary.json",
                  json.dumps(res, ensure_ascii=False, indent=1, default=str))

    payload = json.dumps(res, ensure_ascii=False, separators=(",", ":"), default=str)
    payload = payload.replace("</", "<\\/")
    template = resources.files("ladestatistik").joinpath("templates/dashboard.html").read_text(
        encoding="utf-8")
    page = template.replace("/*__DATA__*/", payload)
    page = page.replace("<title>Ladestatistik Muttenz</title>",
                        f"<title>{htmllib.escape(cfg.public_title)}</title>")
    if not cfg.allow_indexing:
        page = page.replace('<meta charset="utf-8">',
                            '<meta charset="utf-8">\n<meta name="robots" content="noindex">', 1)
    _atomic_write(report / "index.html", page)

    _atomic_write(root / "index.html", _landing(cfg, f"/{cfg.report_path}/"))
    _atomic_write(root / "reports" / "index.html", _landing(cfg, f"/{cfg.report_path}/"))
    _atomic_write(root / "version.json", json.dumps(
        {**res["version"], "generated_at": int(time.time())}, ensure_ascii=False))
    _atomic_write(root / "robots.txt",
                  "User-agent: *\n" + ("Allow: /\n" if cfg.allow_indexing else "Disallow: /\n"))
    return report / "index.html"
