"""Einheitlicher Katalog aller Ladepunkte (EVSE) aus OCPI und OICP."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import geo, sources
from .sources import normalize_evse_id
from .tariffs import WEEKDAYS_DE, summarize, tariff_key

log = logging.getLogger(__name__)


@dataclass
class Evse:
    evse_id: str
    operator: str = ""
    owner: str = ""
    site_key: str = ""
    site_name: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None
    power_kw: float | None = None
    power_type: str = ""
    connectors: str = ""
    access: str = ""
    opening: str = ""
    in_ocpi: bool = False
    in_oicp: bool = False
    ocpi_country: str = ""
    ocpi_party: str = ""
    ocpi_location: str = ""
    ocpi_uid: str = ""
    tariff_keys: list[str] = field(default_factory=list)
    status_ocpi: str = ""
    status_oicp: str = ""
    distance_m: float | None = None
    in_municipality: bool = False

    @property
    def is_dc(self) -> bool:
        return self.power_type.upper().startswith("DC")

    @property
    def ocpi_key(self) -> tuple[str, str, str] | None:
        """(country, party, evse_uid) – Schlüssel der OCPI-Status-Datensätze."""
        if not self.in_ocpi:
            return None
        return (self.ocpi_country, self.ocpi_party, self.ocpi_uid)


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _opening_ocpi(ot: dict | None) -> str:
    if not ot or ot.get("twentyfourseven"):
        return "24/7" if ot else ""
    by_period: dict[str, list[int]] = {}
    for rh in ot.get("regular_hours") or []:
        by_period.setdefault(f"{rh['period_begin']}–{rh['period_end']}", []).append(
            int(rh["weekday"]))
    parts = []
    for period, days in by_period.items():
        days = sorted(set(days))
        label = (f"{WEEKDAYS_DE[days[0] - 1]}–{WEEKDAYS_DE[days[-1] - 1]}"
                 if len(days) > 2 and days == list(range(days[0], days[-1] + 1))
                 else ",".join(WEEKDAYS_DE[d - 1] for d in days))
        parts.append(f"{label} {period}")
    return "; ".join(parts)


def _from_ocpi(loc: dict) -> list[Evse]:
    out = []
    cc, pid = loc.get("country_code", ""), loc.get("party_id", "")
    try:
        lat = float(loc["coordinates"]["latitude"])
        lon = float(loc["coordinates"]["longitude"])
    except (KeyError, TypeError, ValueError):
        lat = lon = None
    postal = _clean(loc.get("postal_code"))
    city = _clean(loc.get("city"))
    city = re.sub(r"^\d{4}\s+", "", city)  # "4132 Muttenz" -> "Muttenz"
    # operator ist bei JOYA-Stationen immer "JOYA (swisscharge)" -> suboperator aussagekräftiger
    operator = (_clean((loc.get("suboperator") or {}).get("name"))
                or _clean((loc.get("operator") or {}).get("name")) or f"{cc}*{pid}")
    owner = _clean((loc.get("owner") or {}).get("name"))
    for e in loc.get("evses") or []:
        conns = e.get("connectors") or []
        power = max((c.get("max_electric_power") or 0 for c in conns), default=0) / 1000
        ptypes = {c.get("power_type") or "" for c in conns}
        evse_id = normalize_evse_id(e.get("evse_id") or f"{cc}*{pid}*{e['uid']}")
        tkeys = sorted({tariff_key(cc, pid, t) for c in conns for t in c.get("tariff_ids") or []})
        out.append(Evse(
            evse_id=evse_id, operator=operator, owner=owner,
            site_key=f"ocpi:{cc}*{pid}*{loc.get('id')}",
            site_name=_clean(loc.get("name")) or _clean(loc.get("address")),
            address=_clean(loc.get("address")), postal_code=postal, city=city,
            lat=lat, lon=lon, power_kw=power or None,
            power_type="DC" if "DC" in ptypes else
                       ("AC_3_PHASE" if "AC_3_PHASE" in ptypes else next(iter(ptypes), "")),
            connectors=",".join(sorted({c.get("standard") or "" for c in conns})),
            opening=_opening_ocpi(loc.get("opening_times")),
            in_ocpi=True, ocpi_country=cc, ocpi_party=pid,
            ocpi_location=str(loc.get("id")), ocpi_uid=str(e.get("uid")),
            tariff_keys=tkeys, status_ocpi=e.get("status") or "",
        ))
    return out


def _oicp_score(rec: dict) -> int:
    evse_prefix = "*".join(normalize_evse_id(rec["EvseID"]).split("*")[:2])
    score = 2 if (rec.get("_operator_id") or "").upper() == evse_prefix else 0
    return score + (1 if rec.get("ChargingStationNames") else 0)


def _from_oicp(rec: dict) -> Evse:
    addr = rec.get("Address") or {}
    try:
        lat, lon = map(float, (rec.get("GeoCoordinates") or {}).get("Google", "").split())
    except ValueError:
        lat = lon = None
    names = rec.get("ChargingStationNames") or []
    if isinstance(names, dict):
        names = [names]
    name = next((n.get("value") for n in names if n.get("lang") == "de"),
                names[0].get("value") if names else "")
    fac = rec.get("ChargingFacilities") or []
    powers = []
    for f in fac:
        try:
            powers.append(float(f.get("power") or 0))
        except ValueError:
            pass
    ptypes = {str(f.get("powertype") or "") for f in fac}
    street = _clean(addr.get("Street"))
    postal = _clean(addr.get("PostalCode"))
    return Evse(
        evse_id=normalize_evse_id(rec["EvseID"]),
        operator=_clean(rec.get("_operator_name")),
        site_key=f"oicp:{rec.get('_operator_id')}:{street.lower()}:{postal}",
        site_name=_clean(name) or street,
        address=street, postal_code=postal, city=_clean(addr.get("City")),
        lat=lat, lon=lon, power_kw=max(powers) if powers else None,
        power_type="DC" if any(p.startswith("DC") for p in ptypes)
                   else ("AC_3_PHASE" if "AC_3_PHASE" in ptypes else next(iter(ptypes), "")),
        connectors=",".join(rec.get("Plugs") or []),
        access=_clean(rec.get("Accessibility")),
        opening="24/7" if rec.get("IsOpen24Hours") else "eingeschränkt",
        in_oicp=True,
    )


def build(ocpi_locations: list[dict] | None, oicp_records: list[dict] | None,
          oicp_status: dict[str, str] | None = None) -> dict[str, Evse]:
    """Führt beide Quellen zusammen (Schlüssel: normalisierte EVSE-ID)."""
    cat: dict[str, Evse] = {}
    for loc in ocpi_locations or []:
        if loc.get("publish") is False:
            continue
        for e in _from_ocpi(loc):
            cat[e.evse_id] = e
    best: dict[str, dict] = {}
    for rec in oicp_records or []:
        eid = normalize_evse_id(rec.get("EvseID", ""))
        if eid and (eid not in best or _oicp_score(rec) > _oicp_score(best[eid])):
            best[eid] = rec
    for eid, rec in best.items():
        o = _from_oicp(rec)
        if eid in cat:
            e = cat[eid]
            e.in_oicp = True
            e.access = o.access
        else:
            cat[eid] = o
    for eid, st in (oicp_status or {}).items():
        if eid in cat:
            cat[eid].status_oicp = st
    return cat


def annotate(cat: dict[str, Evse], lat: float, lon: float,
             municipality_geometry: dict | None = None) -> None:
    for e in cat.values():
        if e.lat is None or e.lon is None:
            continue
        e.distance_m = round(geo.haversine_m(lat, lon, e.lat, e.lon))
        if municipality_geometry:
            e.in_municipality = geo.point_in_geometry(e.lat, e.lon, municipality_geometry)


def fetch_all(with_oicp: bool = True):
    """Lädt Standorte, Tarife und (optional) OICP-Daten. Fehler einer Quelle sind
    nicht fatal, solange die andere Quelle verfügbar ist."""
    locs = tariffs = oicp = oicp_status = None
    try:
        locs = sources.fetch_ocpi_locations()
        tariffs = sources.fetch_ocpi_tariffs()
    except Exception as exc:  # noqa: BLE001
        log.error("OCPI-API nicht verfügbar: %s", exc)
    if with_oicp:
        try:
            oicp = sources.fetch_oicp_static()
            oicp_status = sources.fetch_oicp_status()
        except Exception as exc:  # noqa: BLE001
            log.error("OICP-Dateien nicht verfügbar: %s", exc)
    if locs is None and oicp is None:
        raise RuntimeError("Keine Datenquelle verfügbar")
    tmap = {tariff_key(t["country_code"], t["party_id"], t["id"]): t for t in tariffs or []}
    return build(locs, oicp, oicp_status), tmap


CSV_FIELDS = ["distance_m", "in_municipality", "evse_id", "operator", "owner", "site_name", "address",
              "postal_code", "city", "power_kw", "power_type", "connectors", "access",
              "opening", "in_ocpi", "in_oicp", "ocpi_country", "ocpi_party", "ocpi_location",
              "ocpi_uid", "status_ocpi", "status_oicp", "lat", "lon", "tariff_keys",
              "tariff", "energy_chf_kwh", "time_chf_h", "blocking_chf_h", "blocking_after_min",
              "flat_chf"]


def evse_row(e: Evse, tmap: dict[str, dict]) -> dict:
    t = next((tmap[k] for k in e.tariff_keys if k in tmap), None)
    s = summarize(t)
    if not t and e.tariff_keys:
        s["description"] = f"Tarif-ID {', '.join(e.tariff_keys)} noch nicht in der API"
    elif not t:
        s["description"] = "keine Tarifangabe (nur OICP)" if not e.in_ocpi else "kein Tarif"
    row = asdict(e)
    row["tariff_keys"] = ";".join(e.tariff_keys)
    row["tariff"] = s.pop("description")
    row.update(s)
    return row


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
