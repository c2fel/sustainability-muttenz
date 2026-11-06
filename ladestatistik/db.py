"""SQLite-Speicher. Alle Zeitstempel sind Unix-Sekunden (UTC).

Status wird als *Intervalle* (``status_run``) gespeichert: eine Zeile pro
zusammenhängendem Zeitraum mit gleichem Status. Fällt der Collector aus,
entsteht eine Lücke (kein Intervall), statt dass ein veralteter Status
weitergeschrieben wird.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS evse (
    evse_id TEXT PRIMARY KEY,
    operator TEXT, owner TEXT, site_key TEXT, site_name TEXT, address TEXT, postal_code TEXT, city TEXT,
    lat REAL, lon REAL, power_kw REAL, power_type TEXT, connectors TEXT, access TEXT,
    opening TEXT, in_ocpi INTEGER, in_oicp INTEGER, ocpi_country TEXT, ocpi_party TEXT,
    ocpi_location TEXT, ocpi_uid TEXT, distance_m REAL, in_municipality INTEGER,
    is_focus INTEGER, first_seen INTEGER, last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS status_run (
    id INTEGER PRIMARY KEY,
    evse_id TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'ocpi' | 'oicp'
    status TEXT NOT NULL,          -- normalisiert (status.py)
    status_raw TEXT,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    src_ts INTEGER                 -- last_updated laut CPO (nur OCPI)
);
CREATE INDEX IF NOT EXISTS ix_run_evse ON status_run(evse_id, source, start_ts);
CREATE INDEX IF NOT EXISTS ix_run_end ON status_run(end_ts);
CREATE TABLE IF NOT EXISTS poll (
    ts INTEGER, kind TEXT, ok INTEGER, n INTEGER, ms INTEGER, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_poll ON poll(kind, ts);
CREATE TABLE IF NOT EXISTS tariff_version (
    tariff_key TEXT, hash TEXT, first_seen INTEGER, last_seen INTEGER,
    last_updated TEXT, json TEXT,
    PRIMARY KEY (tariff_key, hash)
);
CREATE TABLE IF NOT EXISTS evse_tariff (
    evse_id TEXT, tariff_key TEXT, first_seen INTEGER, last_seen INTEGER,
    PRIMARY KEY (evse_id, tariff_key)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

EVSE_COLS = ["evse_id", "operator", "owner", "site_key", "site_name", "address", "postal_code", "city",
             "lat", "lon", "power_kw", "power_type", "connectors", "access", "opening",
             "in_ocpi", "in_oicp", "ocpi_country", "ocpi_party", "ocpi_location", "ocpi_uid",
             "distance_m", "in_municipality", "is_focus"]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def meta_get(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(conn, key: str, value) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def tariff_hash(t: dict) -> str:
    content = {k: v for k, v in t.items() if k not in ("last_updated",)}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def upsert_tariff(conn, key: str, tariff: dict, ts: int) -> bool:
    """Speichert eine Tarifversion. ``True`` falls neu (Preisänderung)."""
    h = tariff_hash(tariff)
    cur = conn.execute("UPDATE tariff_version SET last_seen=? WHERE tariff_key=? AND hash=?",
                       (ts, key, h))
    if cur.rowcount:
        return False
    conn.execute("INSERT INTO tariff_version VALUES (?,?,?,?,?,?)",
                 (key, h, ts, ts, tariff.get("last_updated"), json.dumps(tariff)))
    return True


def upsert_evse_tariff(conn, evse_id: str, key: str, ts: int) -> None:
    conn.execute(
        "INSERT INTO evse_tariff VALUES (?,?,?,?) ON CONFLICT(evse_id, tariff_key) "
        "DO UPDATE SET last_seen=excluded.last_seen", (evse_id, key, ts, ts))
