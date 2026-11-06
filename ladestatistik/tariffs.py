"""OCPI-Tarife: Kennzahlen, Klartext-Beschreibung und Kosten für Referenz-Ladevorgänge.

Vereinfachte Implementierung der OCPI-2.2.1/2.3.0-Preislogik:

* Pro Dimension (ENERGY, TIME, PARKING_TIME, FLAT) gilt jeweils das *erste*
  TariffElement, dessen Restriktionen zutreffen und das eine Komponente dieses
  Typs enthält.
* Restriktionen: start/end_time, start/end_date, day_of_week, min/max_kwh,
  min/max_power, min/max_duration (Elemente mit ``reservation`` werden ignoriert).
* ``step_size`` wird pro Element und Dimension auf die Summe aufgerundet.
* MWST: ``tax_included = YES/N/A`` → Preis ist brutto, sonst wird ``vat`` addiert.

Hinweis zu TIME: Laut OCPI zählt TIME nur während des Ladens. Viele Schweizer
CPOs verwenden TIME aber für die gesamte Anschlussdauer (z.B. Blockiergebühr
"ab 4 h"). Standard ist daher ``time_mode="session"``; ``"charging"`` folgt
der Spezifikation strikt.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Zurich")
except Exception:  # pragma: no cover - fehlende tzdata
    TZ = dt.timezone(dt.timedelta(hours=1))

WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
DIMENSIONS = ("ENERGY", "TIME", "PARKING_TIME")


@dataclass
class RefSession:
    """Typischer Ladevorgang zum Vergleich von Tarifen."""
    id: str
    label: str
    weekday: int          # 0 = Montag
    start: str            # "HH:MM" Lokalzeit
    duration_min: int
    energy_kwh: float
    max_power_kw: float = 11.0

    def start_dt(self, ref_date: dt.date | None = None) -> dt.datetime:
        ref_date = ref_date or dt.date(2026, 11, 2)  # ein Montag
        d = ref_date + dt.timedelta(days=(self.weekday - ref_date.weekday()) % 7)
        h, m = map(int, self.start.split(":"))
        return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


DEFAULT_REF_SESSIONS = [
    RefSession("kurz", "Einkauf: Sa 10:00, 1 h, 10 kWh", 5, "10:00", 60, 10),
    RefSession("pendler", "Pendler: Di 07:00, 9 h, 25 kWh", 1, "07:00", 540, 25),
    RefSession("nacht", "Anwohner: Mi 19:00, 12 h, 30 kWh", 2, "19:00", 720, 30),
    RefSession("schnell", "Schnellladen: Do 14:00, 30 min, 25 kWh", 3, "14:00", 30, 25, 150),
]


def tariff_key(country_code: str, party_id: str, tariff_id: str) -> str:
    return f"{country_code}*{party_id}*{tariff_id}"


def from_simple(spec: dict) -> dict:
    """Manuell erfasster Tarif (Bruttopreise) -> OCPI-Tarifobjekt.

    Felder: ``energy_chf_kwh``, ``time_chf_h``, ``blocking_chf_h``,
    ``blocking_after_min``, ``blocking_start``/``blocking_end`` (HH:MM, optional),
    ``flat_chf``.
    """
    elements = []
    after = spec.get("blocking_after_min")
    if spec.get("blocking_chf_h") and after:
        # bis zur Blockierzeit gilt der normale Zeitpreis (oder 0); danach blocking_chf_h
        r_free = {"max_duration": int(after) * 60}
        elements.append({"price_components": [{"type": "TIME", "step_size": 60,
                                               "price": spec.get("time_chf_h") or 0}],
                         "restrictions": r_free})
        r_block = {}
        if spec.get("blocking_start"):
            r_block["start_time"] = spec["blocking_start"]
            r_block["end_time"] = spec.get("blocking_end", "24:00")
        elements.append({"price_components": [{"type": "TIME", "price": spec["blocking_chf_h"],
                                               "step_size": 60}],
                         "restrictions": r_block or None})
    base = []
    if spec.get("flat_chf"):
        base.append({"type": "FLAT", "price": spec["flat_chf"], "step_size": 1})
    if spec.get("energy_chf_kwh") is not None:
        base.append({"type": "ENERGY", "price": spec["energy_chf_kwh"], "step_size": 1})
    if spec.get("time_chf_h"):
        base.append({"type": "TIME", "price": spec["time_chf_h"], "step_size": 60})
    elements.append({"price_components": base})
    return {"id": spec.get("id", "manual"), "currency": "CHF", "tax_included": "YES",
            "elements": elements, "_manual_source": spec.get("source"),
            "last_updated": spec.get("valid_from")}


# --------------------------------------------------------------------------- MWST

def _gross_factor(tariff: dict, component: dict) -> float:
    if str(tariff.get("tax_included") or "").upper() in ("YES", "N/A"):
        return 1.0
    vat = component.get("vat")
    return 1.0 + (float(vat) / 100.0 if vat is not None else 0.0)


def gross_price(tariff: dict, component: dict) -> float:
    return float(component.get("price") or 0.0) * _gross_factor(tariff, component)


# ------------------------------------------------------------------- Restriktionen

def _hm_in(hm: str, start: str | None, end: str | None) -> bool:
    start = start or "00:00"
    end = end or "24:00"
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end  # über Mitternacht


def restriction_matches(r: dict | None, *, local: dt.datetime, elapsed_s: float,
                        kwh: float, power_kw: float) -> bool:
    if not r:
        return True
    if r.get("reservation"):
        return False
    if (r.get("start_time") or r.get("end_time")) and \
            not _hm_in(local.strftime("%H:%M"), r.get("start_time"), r.get("end_time")):
        return False
    day = local.date().isoformat()
    if r.get("start_date") and day < r["start_date"]:
        return False
    if r.get("end_date") and day >= r["end_date"]:
        return False
    if r.get("day_of_week") and WEEKDAYS[local.weekday()] not in r["day_of_week"]:
        return False
    if r.get("min_kwh") is not None and kwh < float(r["min_kwh"]):
        return False
    if r.get("max_kwh") is not None and kwh >= float(r["max_kwh"]):
        return False
    if r.get("min_power") is not None and power_kw < float(r["min_power"]):
        return False
    if r.get("max_power") is not None and power_kw >= float(r["max_power"]):
        return False
    if r.get("min_duration") is not None and elapsed_s < float(r["min_duration"]):
        return False
    if r.get("max_duration") is not None and elapsed_s >= float(r["max_duration"]):
        return False
    return True


def _first_element(elements: list[dict], ctype: str, **ctx) -> int | None:
    for i, el in enumerate(elements):
        if any(pc.get("type") == ctype for pc in el.get("price_components") or []) and \
                restriction_matches(el.get("restrictions"), **ctx):
            return i
    return None


def _component(element: dict, ctype: str) -> dict:
    return next(pc for pc in element["price_components"] if pc.get("type") == ctype)


# ----------------------------------------------------------------- Kostenrechnung

def price_session(tariff: dict, session: RefSession, evse_power_kw: float | None = None,
                  time_mode: str = "session", ref_date: dt.date | None = None) -> dict:
    """Bruttokosten (CHF inkl. MWST) eines Referenz-Ladevorgangs."""
    elements = tariff.get("elements") or []
    power = session.max_power_kw
    if evse_power_kw:
        power = min(power, evse_power_kw)
    total_s = session.duration_min * 60
    charge_s = min(total_s, session.energy_kwh / power * 3600) if power > 0 else 0
    delivered = power * charge_s / 3600
    start = session.start_dt(ref_date)

    qty: dict[tuple[int, str], float] = defaultdict(float)
    step = 60
    for t in range(0, total_s, step):
        dt_s = min(step, total_s - t)
        local = (start + dt.timedelta(seconds=t)).astimezone(TZ)
        charging_s = max(0.0, min(charge_s, t + dt_s) - t)
        ctx = dict(local=local, elapsed_s=t, kwh=power * min(t, charge_s) / 3600,
                   power_kw=power if charging_s > 0 else 0.0)
        amounts = {
            "ENERGY": charging_s * power / 3600,
            "TIME": dt_s if time_mode == "session" else charging_s,
            "PARKING_TIME": dt_s - charging_s,
        }
        for ctype, amount in amounts.items():
            if amount <= 0:
                continue
            idx = _first_element(elements, ctype, **ctx)
            if idx is not None:
                qty[(idx, ctype)] += amount

    breakdown = defaultdict(float)
    for (idx, ctype), amount in qty.items():
        pc = _component(elements[idx], ctype)
        step_size = float(pc.get("step_size") or 1)
        if ctype == "ENERGY":
            units = math.ceil(round(amount * 1000 / step_size, 6)) * step_size / 1000  # kWh
        else:
            units = math.ceil(round(amount / step_size, 6)) * step_size / 3600       # h
        breakdown[ctype] += units * gross_price(tariff, pc)

    flat_idx = _first_element(elements, "FLAT", local=start, elapsed_s=0, kwh=0,
                              power_kw=power)
    if flat_idx is not None:
        breakdown["FLAT"] += gross_price(tariff, _component(elements[flat_idx], "FLAT"))

    total = sum(breakdown.values())
    lo, hi = tariff.get("min_price"), tariff.get("max_price")
    if lo and lo.get("incl_vat") is not None:
        total = max(total, float(lo["incl_vat"]))
    if hi and hi.get("incl_vat") is not None:
        total = min(total, float(hi["incl_vat"]))
    return {
        "session": session.id,
        "total_chf": round(total, 2),
        "energy_kwh": round(delivered, 2),
        "chf_per_kwh": round(total / delivered, 3) if delivered else None,
        "breakdown": {k: round(v, 2) for k, v in breakdown.items()},
    }


# ----------------------------------------------------------- Kennzahlen & Klartext

def _fmt_h(seconds: float) -> str:
    h = seconds / 3600
    return f"{h:g} h" if h >= 1 else f"{seconds / 60:g} min"


def _describe_restrictions(r: dict | None) -> str:
    if not r:
        return ""
    parts = []
    if r.get("min_duration"):  # 0 = ab Beginn, nicht erwähnen
        parts.append(f"ab {_fmt_h(float(r['min_duration']))}")
    if r.get("max_duration") is not None:
        parts.append(f"bis {_fmt_h(float(r['max_duration']))}")
    if r.get("start_time") or r.get("end_time"):
        parts.append(f"{r.get('start_time') or '00:00'}–{r.get('end_time') or '24:00'}")
    if r.get("day_of_week") and len(r["day_of_week"]) < 7:
        parts.append(",".join(WEEKDAYS_DE[WEEKDAYS.index(d)] for d in r["day_of_week"]
                              if d in WEEKDAYS))
    if r.get("min_kwh") is not None:
        parts.append(f"ab {r['min_kwh']} kWh")
    if r.get("max_kwh") is not None:
        parts.append(f"bis {r['max_kwh']} kWh")
    if r.get("min_power") is not None or r.get("max_power") is not None:
        parts.append(f"{r.get('min_power') or 0}–{r.get('max_power') or '∞'} kW")
    if r.get("start_date") or r.get("end_date"):
        parts.append(f"{r.get('start_date') or ''}..{r.get('end_date') or ''}")
    if r.get("reservation"):
        parts.append("Reservation")
    return ", ".join(parts)


_FREE = {"ENERGY": "Energie", "TIME": "Zeit", "PARKING_TIME": "Parkieren", "FLAT": "Start"}
_UNIT = {"ENERGY": "CHF/kWh", "TIME": "CHF/h", "PARKING_TIME": "CHF/h Parkieren",
         "FLAT": "CHF pro Vorgang"}


def describe(tariff: dict | None) -> str:
    """Kurze deutsche Beschreibung, Preise inkl. MWST."""
    if not tariff:
        return "Tarif nicht in der API"
    out = []
    for el in tariff.get("elements") or []:
        restr = _describe_restrictions(el.get("restrictions"))
        comps = [f"{gross_price(tariff, pc):.2f} {_UNIT.get(pc.get('type'), pc.get('type'))}"
                 if float(pc.get("price") or 0) > 0
                 else f"{_FREE.get(pc.get('type'), pc.get('type'))} gratis"
                 for pc in el.get("price_components") or []
                 if float(pc.get("price") or 0) > 0 or restr]  # Gratis-Fenster zeigen
        if not comps:
            continue
        out.append(" + ".join(comps) + (f" ({restr})" if restr else ""))
    return "; ".join(out) or "gratis"


def summarize(tariff: dict | None) -> dict:
    """Kennzahlen für Tabellen/Regression (brutto)."""
    res = {"energy_chf_kwh": None, "time_chf_h": None, "blocking_chf_h": None,
           "blocking_after_min": None, "flat_chf": None, "description": describe(tariff)}
    if not tariff:
        return res
    free_time_until = None
    for el in tariff.get("elements") or []:
        r = el.get("restrictions") or {}
        for pc in el.get("price_components") or []:
            t, p = pc.get("type"), gross_price(tariff, pc)
            if t == "ENERGY" and res["energy_chf_kwh"] is None:
                res["energy_chf_kwh"] = round(p, 4)
            elif t == "FLAT" and p > 0 and res["flat_chf"] is None:
                res["flat_chf"] = round(p, 2)
            elif t in ("TIME", "PARKING_TIME"):
                if r.get("max_duration") is not None and not r.get("min_duration"):
                    # Zeitfenster "bis X" -> danach folgt typischerweise die Blockiergebühr
                    free_time_until = float(r["max_duration"])
                    if p > 0 and t == "TIME" and res["time_chf_h"] is None:
                        res["time_chf_h"] = round(p, 2)
                elif p > 0 and (r.get("min_duration") or free_time_until):
                    if res["blocking_chf_h"] is None:
                        res["blocking_chf_h"] = round(p, 2)
                        after = r.get("min_duration", free_time_until)
                        res["blocking_after_min"] = round(float(after) / 60)
                elif p > 0 and t == "TIME" and res["time_chf_h"] is None:
                    res["time_chf_h"] = round(p, 2)
                elif p > 0 and t == "PARKING_TIME" and res["blocking_chf_h"] is None:
                    res["blocking_chf_h"] = round(p, 2)
                    res["blocking_after_min"] = 0
    return res
