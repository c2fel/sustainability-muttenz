"""Preis-Watcher: liest die offiziellen Preisseiten der Betreiber (Webscraping) und
vergleicht sie mit den manuell erfassten Tarifen in ``tarife.toml``.

Der Watcher ändert ``tarife.toml`` nie selbst. Er meldet Abweichungen, damit eine
Person den neuen Preis prüft und als neuen Eintrag (neues ``valid_from``) erfasst.

Quellen (Stand November 2026, alle Preise inkl. MWST):

* ``migrol``      Migros M-Charge, Preistabelle nach Leistungsklasse (gilt auch ohne Konto)
* ``energie360``  Energie 360°/Joya (Coop-Standorte, Standard ad hoc), AC / Slow DC / Fast DC
* ``iwb``         IWB öffentliches Laden (Allmend Basel-Stadt), AC / DC bis 50 / bis 150 kW
* ``shell``       Shell Recharge Schweiz (ehem. evpass), Modell "Ohne App: QR/Terminal"

Verknüpfung in ``tarife.toml`` über ``watch``, z.B.::

    watch = { energy_chf_kwh = "migrol:lt22" }

Seitenstruktur kann sich ändern: Ein Parser, der nichts mehr findet, meldet einen
Fehler statt einen falschen Preis.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import http

NUM = r"(\d+(?:[.,]\d+)?)"


def _text(raw: str) -> list[str]:
    """HTML -> nicht-leere Textzeilen."""
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>|</td>|</th>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s))
    return [re.sub(r"\s+", " ", line).strip() for line in s.split("\n") if line.strip()]


def _f(x: str) -> float:
    return float(x.replace(",", "."))


# ------------------------------------------------------------------ Parser

def parse_migrol(raw: str) -> dict[str, float]:
    """Tabelle "M-Charge < 22 kW | CHF 0.38" -> {"lt22": 0.38, ...}."""
    lines = _text(raw)
    out = {}
    for i, line in enumerate(lines):
        m = re.fullmatch(r"M-Charge < (\d+) kW", line)
        if m and i + 1 < len(lines):
            p = re.fullmatch(r"CHF " + NUM, lines[i + 1])
            if p:
                out[f"lt{m.group(1)}"] = _f(p.group(1))
    return out


def parse_energie360(raw: str) -> dict[str, float]:
    """Drei Spalten (AC ≤ 22 kW, Slow DC < 100 kW, Fast DC ≥ 100 kW), je ein Block
    "Je nach Standort: … Blockiergebühren CHF x.-/h nach N Stunden"."""
    lines = _text(raw)
    out: dict[str, float] = {}
    cols = ["ac", "dc_slow", "dc_fast"]
    col = -1
    for i, line in enumerate(lines):
        if line.startswith("Je nach Standort") and col < len(cols) - 1:
            col += 1
            continue
        if col < 0:
            continue
        key = cols[col]
        m = re.match(r"CHF " + NUM + r"/kWh.*\((Coop-Standorte|Standard-Preis ad-hoc|"
                     r"Standard-Preis registrierte)", line)
        if m:
            kind = {"Coop-Standorte": "coop", "Standard-Preis ad-hoc": "adhoc",
                    "Standard-Preis registrierte": "registered"}[m.group(2)]
            out.setdefault(f"{key}.{kind}", _f(m.group(1)))
        b = re.match(r"CHF " + NUM + r"\.?-?/h nach " + NUM + r" Stunden?", line)
        if b and f"{key}.blocking_chf_h" not in out:
            out[f"{key}.blocking_chf_h"] = _f(b.group(1))
            out[f"{key}.blocking_after_min"] = _f(b.group(2)) * 60
        if line.startswith("Für charge@") and col == len(cols) - 1:
            break
    return out


def parse_iwb(raw: str) -> dict[str, float]:
    """Tabelle "AC | 48 Rp. | Keine", "DC bis 50 kW | 60 Rp. | Nach 150 Minuten: 15 Rp. pro Minute"."""
    lines = _text(raw)
    out: dict[str, float] = {}
    rows = {"AC": "ac", "DC bis 50 kW": "dc50", "DC bis 150 kW": "dc150"}
    for i, line in enumerate(lines):
        key = rows.get(line)
        if not key or i + 2 >= len(lines):
            continue
        p = re.fullmatch(NUM + r" Rp\.", lines[i + 1])
        if not p:
            continue
        out[f"{key}.energy"] = round(_f(p.group(1)) / 100, 4)
        b = re.match(r"Nach " + NUM + r" Minuten: " + NUM + r" Rp\. pro Minute", lines[i + 2])
        if b:
            out[f"{key}.blocking_after_min"] = _f(b.group(1))
            out[f"{key}.blocking_chf_h"] = round(_f(b.group(2)) * 60 / 100, 2)
        elif lines[i + 2].lower().startswith("keine"):
            out[f"{key}.blocking_chf_h"] = 0.0
    return out


def parse_shell(raw: str) -> dict[str, float]:
    """AEM-JSON der Seite "Ladetarife": Kacheln "Mit Shell App & Ladekarte / Ohne
    Abonnement", "… e-Deal" und "Ohne App / QR-Code oder Zahlungsterminal"."""
    texts: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and "kW" in x:
            texts.append(re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", x))))

    walk(json.loads(raw))
    out: dict[str, float] = {}
    for t in texts:
        if "QR-Code oder Zahlungsterminal" in t:
            model = "adhoc"
        elif "e-Deal" in t and "Monat" in t:
            model = "edeal"
        elif "Ohne Abonnement" in t:
            model = "app"
        else:
            continue
        le = re.search(r"≤ ?22 kW\s*ab CHF " + NUM, t)
        gt = re.search(r"> ?22 kW\s*ab CHF " + NUM, t)
        if le:
            out[f"{model}.le22"] = _f(le.group(1))
        if gt:
            out[f"{model}.gt22"] = _f(gt.group(1))
    return out


@dataclass
class Source:
    id: str
    operator: str
    url: str
    parse: Callable[[str], dict[str, float]]
    expect: tuple[str, ...]   # Schlüssel, die vorhanden sein müssen (sonst Layout geändert)


SOURCES = [
    Source("migrol", "Migros M-Charge (Migrol)", "https://www.migrol.ch/migros-aufladen",
           parse_migrol, ("lt22",)),
    Source("energie360", "Energie 360° / Joya (Coop)",
           "https://www.energie360.ch/de/leistungen/mobilitaet/easycharge/",
           parse_energie360, ("ac.coop", "ac.adhoc")),
    Source("iwb", "IWB", "https://www.iwb.ch/servicecenter/oeffentliches-ladenetz/mobilitaet-tarife",
           parse_iwb, ("ac.energy", "dc50.energy")),
    Source("shell", "Shell Recharge (ehem. evpass)",
           "https://www.shell.ch/de_ch/laden/ladetarife-fuer-ihr-elektroauto.model.json",
           parse_shell, ("adhoc.le22", "adhoc.gt22")),
]


def fetch_all(sources=SOURCES) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out = {}
    for s in sources:
        res = {"operator": s.operator, "url": s.url, "fetched_at": now}
        try:
            body = http.get(s.url, accept="text/html,application/json").body.decode("utf-8", "replace")
            values = s.parse(body)
            missing = [k for k in s.expect if k not in values]
            res["values"] = values
            if missing:
                res["error"] = f"Seitenstruktur geändert? Nicht gefunden: {', '.join(missing)}"
        except Exception as exc:  # noqa: BLE001
            res["error"] = repr(exc)
        out[s.id] = res
    return out


def save_snapshot(result: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{dt.date.today().isoformat()}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def compare(specs: list[dict], result: dict) -> list[dict]:
    """Vergleicht pro EVSE-Gruppe den neuesten Eintrag aus ``tarife.toml`` (auch offene
    Einträge ohne Preis) mit den gescrapten Werten."""
    latest: dict[tuple, dict] = {}
    for spec in specs:
        key = tuple(spec["evse_ids"])
        vf = str(spec.get("valid_from") or "")
        if spec.get("watch") and (key not in latest or vf >= str(latest[key].get("valid_from") or "")):
            latest[key] = spec
    rows = []
    for spec in latest.values():
        for field, ref in spec["watch"].items():
            src, _, k = ref.partition(":")
            r = result.get(src, {})
            scraped = (r.get("values") or {}).get(k)
            current = spec.get(field)
            if scraped is None:
                status = "fehler" if r.get("error") or src in result else "unbekannt"
            elif current is None:
                status = "offen"
            else:
                status = "ok" if abs(float(current) - float(scraped)) < 0.005 else "abweichung"
            rows.append({"site": spec.get("site", ""), "valid_from": spec.get("valid_from"),
                         "field": field, "ref": ref,
                         "tarife_toml": current, "website": scraped, "status": status,
                         "error": r.get("error")})
    return rows
