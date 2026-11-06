"""Geo-Hilfsfunktionen: Distanz, Geokodierung und Gemeindegrenze (geo.admin.ch)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import http

GEOADMIN = "https://api3.geo.admin.ch/rest/services/api"
GEMEINDE_LAYER = "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocode(address: str) -> tuple[float, float, str]:
    """Adresse -> (lat, lon, label) über die swisstopo-Suche (amtliche Gebäudeadressen)."""
    data = http.get_json(f"{GEOADMIN}/SearchServer", params={
        "searchText": address, "type": "locations", "origins": "address", "sr": 4326,
    })
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Adresse nicht gefunden: {address}")
    a = results[0]["attrs"]
    return float(a["lat"]), float(a["lon"]), a.get("label", "")


def municipality_at(lat: float, lon: float, cache: Path | None = None) -> dict:
    """Aktuelle Gemeinde an einem Punkt inkl. Grenzpolygon (GeoJSON, WGS84).

    Rückgabe: ``{"name", "bfs_nr", "kanton", "geometry"}``.
    """
    if cache and cache.exists():
        cached = json.loads(cache.read_text())
        if point_in_geometry(lat, lon, cached.get("geometry")):
            return cached
    data = http.get_json(f"{GEOADMIN}/MapServer/identify", params={
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326,
        "layers": f"all:{GEMEINDE_LAYER}", "tolerance": 0,
        "returnGeometry": "true", "geometryFormat": "geojson",
    })
    current = [r for r in data.get("results", [])
               if (r.get("properties") or r.get("attributes") or {}).get("is_current_jahr")]
    if not current:
        raise ValueError("Keine aktuelle Gemeinde gefunden")
    r = current[0]
    props = r.get("properties") or r.get("attributes") or {}
    out = {"name": props.get("gemname"), "bfs_nr": props.get("gde_nr"),
           "kanton": props.get("kanton"), "geometry": r.get("geometry")}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out))
    return out


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lon: float, geometry: dict | None) -> bool:
    """Punkt-in-Polygon für GeoJSON Polygon/MultiPolygon (mit Löchern)."""
    if not geometry:
        return False
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    polys = [coords] if gtype == "Polygon" else coords if gtype == "MultiPolygon" else []
    for poly in polys:
        if poly and _point_in_ring(lon, lat, poly[0]) and \
                not any(_point_in_ring(lon, lat, hole) for hole in poly[1:]):
            return True
    return False
