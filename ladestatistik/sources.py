"""Datenquellen von ich-tanke-strom.ch (BFE).

1. **OCPI-API** (ab November 2026, offiziell empfohlen)
   ``https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi``
   Module: ``locations``, ``tariffs``, ``status``. Keine Authentifizierung.
   Abdeckung zurzeit: CPOs, die bereits per OCPI liefern (u.a. Swisscharge,
   Energie 360°, IWB, GOFAST, ewz).

2. **OICP-Dateien** (bisheriger Zugang, deckt *alle* CPOs ab, aber keine Tarife)
   - statisch: ``.../data/oicp/ch.bfe.ladestellen-elektromobilitaet.json``
   - dynamisch: ``.../status/oicp/ch.bfe.ladestellen-elektromobilitaet.json``

Doku: https://github.com/SFOE/ichtankestrom_Documentation
Nutzungsbedingungen: Quellenangabe Pflicht; kommerzielle Nutzung nur mit
Bewilligung (ich-tanke-strom@bfe.admin.ch).
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from . import http

log = logging.getLogger(__name__)

OCPI_BASE = "https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi"
OICP_STATIC_URL = ("https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/"
                   "data/oicp/ch.bfe.ladestellen-elektromobilitaet.json")
OICP_STATUS_URL = ("https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/"
                   "status/oicp/ch.bfe.ladestellen-elektromobilitaet.json")

_LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')


def iso_utc(ts: float | dt.datetime) -> str:
    if not isinstance(ts, dt.datetime):
        ts = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _ocpi_paged(path: str, params: dict | None = None, limit: int = 1000) -> list[dict]:
    """Holt alle Seiten einer OCPI-Liste (Pagination über Link-Header)."""
    url = f"{OCPI_BASE}/{path}"
    p = dict(params or {})
    p.setdefault("limit", limit)
    out: list[dict] = []
    next_url: str | None = None
    while True:
        resp = http.get(next_url) if next_url else http.get(url, params=p)
        payload = resp.json()
        if payload.get("status_code") != 1000:
            raise RuntimeError(f"OCPI {path}: {payload.get('status_code')} "
                               f"{payload.get('status_message')}")
        data = payload.get("data") or []
        out.extend(data)
        link = resp.header("link")
        m = _LINK_NEXT.search(link) if link else None
        if not m or not data:
            break
        next_url = m.group(1)
    return out


def fetch_ocpi_locations() -> list[dict]:
    return _ocpi_paged("locations", limit=1000)


def fetch_ocpi_tariffs() -> list[dict]:
    return _ocpi_paged("tariffs", limit=1000)


def fetch_ocpi_status_since(since_ts: float) -> list[dict]:
    """Alle Status-Datensätze, die seit ``since_ts`` empfangen wurden.

    Liefert pro EVSE den *aktuell gespeicherten* Status (keine Historie!).
    Mit einem Zeitpunkt weit in der Vergangenheit erhält man einen
    Vollabzug aller EVSE-Status.
    """
    return _ocpi_paged("status", params={"date_from": iso_utc(since_ts)}, limit=5000)


def fetch_ocpi_status_single(country_code: str, party_id: str,
                             location_id: str, evse_uid: str) -> dict:
    url = f"{OCPI_BASE}/status/{country_code}/{party_id}/{location_id}/evses/{evse_uid}"
    return http.get_json(url)["data"]


def fetch_oicp_static() -> list[dict]:
    """Alle EVSE-Stammdaten (OICP), flach, mit ``_operator_id``/``_operator_name``."""
    payload = http.get_json(OICP_STATIC_URL, timeout=180)
    out = []
    for op in payload.get("EVSEData", []):
        for rec in op.get("EVSEDataRecord") or []:
            rec["_operator_id"] = op.get("OperatorID")
            rec["_operator_name"] = op.get("OperatorName")
            out.append(rec)
    return out


def fetch_oicp_status() -> dict[str, str]:
    """``{EvseID: EVSEStatus}`` für alle EVSEs (OICP)."""
    payload = http.get_json(OICP_STATUS_URL, timeout=120)
    out: dict[str, str] = {}
    for op in payload.get("EVSEStatuses", []):
        for rec in op.get("EVSEStatusRecord") or []:
            out[normalize_evse_id(rec["EvseID"])] = rec["EVSEStatus"]
    return out


def normalize_evse_id(evse_id: str) -> str:
    return (evse_id or "").strip().upper()
