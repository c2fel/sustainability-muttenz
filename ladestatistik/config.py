"""Konfiguration (TOML) mit Standardwerten."""

from __future__ import annotations

import datetime as dt
import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .tariffs import DEFAULT_REF_SESSIONS, RefSession, from_simple

log = logging.getLogger(__name__)

# Felder, von denen mindestens eines gesetzt sein muss, damit ein manueller Tarif gilt
PRICE_FIELDS = ("energy_chf_kwh", "time_chf_h", "blocking_chf_h", "flat_chf")


CONFIDENCE = ("hoch", "mittel", "tief")


@dataclass
class ManualTariff:
    """Manuell erfasster Tarif, gültig ab ``valid_from`` (lokales Datum)."""
    evse_ids: list[str]
    valid_from: str
    tariff: dict
    site: str = ""
    source: str = ""
    confidence: str = ""      # hoch | mittel | tief (Einschätzung der Quelle)
    verified: bool = False    # von einer Person vor Ort / in der App bestätigt


@dataclass
class Config:
    # Standort
    site_name: str = "Bahnhofstrasse 48, Muttenz"
    address: str = "Bahnhofstrasse 48, 4132 Muttenz"
    lat: float = 47.531982
    lon: float = 7.649472
    # Umfang
    municipality: str = "Muttenz"      # Fallback, falls swisstopo nicht erreichbar
    record_municipality: bool = True   # alle Ladepunkte innerhalb der Gemeindegrenze
    record_radius_km: float = 0.0      # optional zusätzlich ein Umkreis (0 = aus)
    focus_radius_m: float = 800.0      # "Nahbereich": Detailauswertung pro Standort
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
    timeline_days: int = 7
    # Manuell erfasste Tarife (aus tarife.toml und/oder [[manual_tariff]] in der Konfiguration)
    manual_file: Path | None = None
    manual_tariffs: list[ManualTariff] = field(default_factory=list)
    manual_open: list[dict] = field(default_factory=list)   # Einträge ohne Preis
    manual_specs: list[dict] = field(default_factory=list)  # alle Rohdaten (Preis-Watcher)
    # Publikation
    out_dir: Path = Path("site")             # Web-Root (stats.jumut.ch)
    report_path: str = "reports/charging"    # Unterpfad des Reports
    base_url: str = "https://stats.jumut.ch"
    public_title: str = "Ladestatistik Muttenz"
    allow_indexing: bool = False

    @property
    def municipality_cache(self) -> Path:
        return self.cache_dir / "gemeinde.json"

    @property
    def report_dir(self) -> Path:
        return self.out_dir / self.report_path.strip("/")

    @property
    def report_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.report_path.strip('/')}/"

    def manual_tariff_for(self, evse_id: str, at: dt.date | None = None) -> ManualTariff | None:
        """Neuester manueller Tarif mit ``valid_from <= at``."""
        at_s = (at or dt.date.today()).isoformat()
        best = None
        for m in self.manual_tariffs:
            if evse_id in m.evse_ids and m.valid_from <= at_s and \
                    (best is None or m.valid_from >= best.valid_from):
                best = m
        return best


def parse_manual(entries: list[dict], origin: str) -> tuple[list[ManualTariff], list[dict]]:
    """Wandelt ``[[manual_tariff]]``-Einträge um. Einträge ohne Preis oder Datum gelten
    als noch offen und werden separat zurückgegeben."""
    done, open_ = [], []
    for spec in entries:
        ids = [e.strip().upper() for e in spec.get("evse_ids", [])]
        if not ids:
            log.warning("%s: Eintrag ohne evse_ids ignoriert", origin)
            continue
        has_price = any(k in spec for k in PRICE_FIELDS)
        valid_from = str(spec.get("valid_from") or "")
        if not has_price or not valid_from:
            open_.append({"site": spec.get("site", ""), "evse_ids": ids})
            continue
        try:
            dt.date.fromisoformat(valid_from)
        except ValueError:
            raise ValueError(f"{origin}: valid_from '{valid_from}' ist kein Datum (JJJJ-MM-TT)")
        conf = str(spec.get("confidence") or "")
        if conf and conf not in CONFIDENCE:
            raise ValueError(f"{origin}: confidence '{conf}' – erlaubt: {', '.join(CONFIDENCE)}")
        tariff = from_simple({**spec, "id": f"manual:{ids[0]}:{valid_from}"})
        tariff.update({"_origin": "manual", "_confidence": conf,
                       "_verified": bool(spec.get("verified", False)), "_url": spec.get("url")})
        done.append(ManualTariff(ids, valid_from, tariff, spec.get("site", ""),
                                 spec.get("source", ""), conf, bool(spec.get("verified", False))))
    return done, open_


def normalize_specs(entries: list[dict]) -> list[dict]:
    return [{**spec, "evse_ids": [e.strip().upper() for e in spec.get("evse_ids", [])],
             "watch": dict(spec.get("watch") or {})} for spec in entries]


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
    cfg.municipality = scope.get("municipality", cfg.municipality)
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
    cfg.db_path = (base / col.get("db_path", str(cfg.db_path))).resolve()
    cfg.cache_dir = (base / col.get("cache_dir", str(cfg.cache_dir))).resolve()

    ana = data.get("analysis", {})
    cfg.time_mode = ana.get("time_mode", cfg.time_mode)
    cfg.min_session_s = int(ana.get("min_session_s", cfg.min_session_s))
    cfg.merge_gap_s = int(ana.get("merge_gap_s", cfg.merge_gap_s))
    cfg.timeline_days = int(ana.get("timeline_days", cfg.timeline_days))
    if ana.get("reference_session"):
        cfg.ref_sessions = [RefSession(**s) for s in ana["reference_session"]]

    entries = list(data.get("manual_tariff", []))
    mfile = data.get("tariffs", {}).get("manual_file")
    if mfile:
        cfg.manual_file = (base / mfile).resolve()
        if cfg.manual_file.exists():
            entries += tomllib.loads(cfg.manual_file.read_text(encoding="utf-8")).get(
                "manual_tariff", [])
        else:
            log.warning("Tarifdatei %s nicht gefunden", cfg.manual_file)
    cfg.manual_tariffs, cfg.manual_open = parse_manual(entries, str(mfile or p))
    cfg.manual_specs = normalize_specs(entries)

    pub = data.get("publish", {})
    cfg.out_dir = (base / pub.get("out_dir", str(cfg.out_dir))).resolve()
    cfg.report_path = pub.get("report_path", cfg.report_path).strip("/")
    cfg.base_url = pub.get("base_url", cfg.base_url)
    cfg.public_title = pub.get("title", cfg.public_title)
    cfg.allow_indexing = bool(pub.get("allow_indexing", cfg.allow_indexing))
    return cfg
