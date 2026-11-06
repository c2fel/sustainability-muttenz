"""Erzeugt das statische Dashboard (``index.html``) und Daten-Downloads.

Ausgabe (Standard ``site/``):
  index.html          Dashboard (eine Datei, Daten eingebettet)
  data/summary.json   Kennzahlen (ohne Tageswerte)
  data/daily.csv      Tageswerte pro Ladepunkt
  data/evses.csv      alle aufgezeichneten Ladepunkte mit Kennzahlen und Tarif
"""

from __future__ import annotations

import csv
import json
import os
import html as htmllib
from importlib import resources
from pathlib import Path

from .analyze import analyze
from .config import Config


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _evse_csv_rows(rows: list[dict], ref_ids: list[str]):
    for r in rows:
        t = r.get("tariff") or {}
        out = {k: r.get(k) for k in (
            "evse_id", "site_name", "address", "operator", "distance_m", "lat", "lon", "power_kw",
            "power_type", "is_focus", "in_municipality", "access", "opening", "source",
            "status_now", "observed_h", "operational_h", "occupied_h", "utilization",
            "availability", "sessions", "sessions_per_day", "median_session_min",
            "p75_session_min", "share_sessions_over_4h")}
        out.update({"tariff": t.get("description"), "energy_chf_kwh": t.get("energy_chf_kwh"),
                    "time_chf_h": t.get("time_chf_h"), "blocking_chf_h": t.get("blocking_chf_h"),
                    "blocking_after_min": t.get("blocking_after_min"),
                    "tariff_manual": r.get("tariff_manual")})
        for rid in ref_ids:
            p = r.get("ref_prices", {}).get(rid) or {}
            out[f"chf_{rid}"] = p.get("total_chf")
            out[f"chf_per_kwh_{rid}"] = p.get("chf_per_kwh")
        yield out


def _write_csv(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    os.replace(tmp, path)


def publish(conn, cfg: Config, days: float = 28, out_dir: Path | None = None) -> Path:
    out = Path(out_dir or cfg.out_dir)
    (out / "data").mkdir(parents=True, exist_ok=True)
    res = analyze(conn, cfg, days=days)
    res["title"] = cfg.public_title

    daily = res.pop("daily")
    evses = res.pop("evses")
    ref_ids = [s.id for s in cfg.ref_sessions]
    _write_csv(out / "data" / "daily.csv", daily)
    _write_csv(out / "data" / "evses.csv", list(_evse_csv_rows(evses, ref_ids)))
    _atomic_write(out / "data" / "summary.json",
                  json.dumps(res, ensure_ascii=False, indent=1, default=str))

    # Dashboard: Streupunkte der Region bleiben drin (für das Diagramm), Rest kompakt
    payload = json.dumps(res, ensure_ascii=False, separators=(",", ":"), default=str)
    payload = payload.replace("</", "<\\/")
    template = resources.files("ladestatistik").joinpath("templates/dashboard.html").read_text(
        encoding="utf-8")
    html = template.replace("/*__DATA__*/", payload)
    html = html.replace("<title>Ladestatistik Muttenz</title>",
                        f"<title>{htmllib.escape(cfg.public_title)}</title>")
    _atomic_write(out / "index.html", html)
    return out / "index.html"
