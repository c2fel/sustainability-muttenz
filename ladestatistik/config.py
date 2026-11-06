"""Konfiguration (TOML) mit Standardwerten."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .tariffs import DEFAULT_REF_SESSIONS, RefSession, from_simple


@dataclass
class Config:
    # Standort
    site_name: str = "Bahnhofstrasse 48, Muttenz"
    address: str = "Bahnhofstrasse 48, 4132 Muttenz"
    lat: float = 47.531982
    lon: float = 7.649472
    # Umfang
    record_radius_km: float = 15.0     # alles in diesem Umkreis wird aufgezeichnet
    record_municipality: bool = True   # plus ganze Gemeinde (Polygon swisstopo)
    focus_radius_m: float = 800.0      # "Nahbereich" für Auswertung/Dashboard
    focus_evse_ids: list[str] = field(default_factory=list)
    exclude_evse_ids: list[str] = field(default_factory=list)
    # Collector
    db_path: Path = Path("data/ladestatistik.sqlite")
    cache_dir: Path = Path("data/cache")
    ocpi_delta_interval_s: int = 60
    ocpi_full_interval_s: int = 900
    oicp_enabled: bool = True
    oicp_interval_s: int = 120
    catalog_interval_s: int = 6 * 3600
    max_gap_s: int = 600
    flush_interval_s: int = 300
    # Auswertung
    time_mode: str = "session"
    ref_sessions: list[RefSession] = field(default_factory=lambda: list(DEFAULT_REF_SESSIONS))
    min_session_s: int = 300
    merge_gap_s: int = 180
    # Manuell erfasste Tarife für Stationen ohne API-Tarif: {EVSE-ID: OCPI-Tarif}
    manual_tariffs: dict[str, dict] = field(default_factory=dict)
    # Publikation
    out_dir: Path = Path("site")
    public_title: str = "Ladestatistik Muttenz"

    @property
    def municipality_cache(self) -> Path:
        return self.cache_dir / "gemeinde.json"


def load(path: str | Path | None) -> Config:
    cfg = Config()
    if not path:
        return cfg
    p = Path(path)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    base = p.resolve().parent

    site = data.get("site", {})
    cfg.site_name = site.get("name", cfg.site_name)
    cfg.address = site.get("address", cfg.address)
    cfg.lat = float(site.get("lat", cfg.lat))
    cfg.lon = float(site.get("lon", cfg.lon))

    scope = data.get("scope", {})
    cfg.record_radius_km = float(scope.get("record_radius_km", cfg.record_radius_km))
    cfg.record_municipality = bool(scope.get("record_municipality", cfg.record_municipality))
    cfg.focus_radius_m = float(scope.get("focus_radius_m", cfg.focus_radius_m))
    cfg.focus_evse_ids = [s.upper() for s in scope.get("focus_evse_ids", [])]
    cfg.exclude_evse_ids = [s.upper() for s in scope.get("exclude_evse_ids", [])]

    col = data.get("collector", {})
    for key in ("ocpi_delta_interval_s", "ocpi_full_interval_s", "oicp_interval_s",
                "catalog_interval_s", "max_gap_s", "flush_interval_s"):
        if key in col:
            setattr(cfg, key, int(col[key]))
    cfg.oicp_enabled = bool(col.get("oicp_enabled", cfg.oicp_enabled))
    if "db_path" in col:
        cfg.db_path = (base / col["db_path"]).resolve()
    else:
        cfg.db_path = (base / cfg.db_path).resolve()
    cfg.cache_dir = (base / col.get("cache_dir", str(cfg.cache_dir))).resolve()

    ana = data.get("analysis", {})
    cfg.time_mode = ana.get("time_mode", cfg.time_mode)
    cfg.min_session_s = int(ana.get("min_session_s", cfg.min_session_s))
    cfg.merge_gap_s = int(ana.get("merge_gap_s", cfg.merge_gap_s))
    if ana.get("reference_session"):
        cfg.ref_sessions = [RefSession(**s) for s in ana["reference_session"]]

    for spec in data.get("manual_tariff", []):
        tariff = from_simple(spec)
        for eid in spec.get("evse_ids", []):
            cfg.manual_tariffs[eid.upper()] = tariff

    pub = data.get("publish", {})
    cfg.out_dir = (base / pub.get("out_dir", str(cfg.out_dir))).resolve()
    cfg.public_title = pub.get("title", cfg.public_title)
    return cfg
