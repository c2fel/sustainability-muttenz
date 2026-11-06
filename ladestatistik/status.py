"""Vereinheitlichung der Status-Werte aus OCPI und OICP."""

AVAILABLE = "available"
OCCUPIED = "occupied"
RESERVED = "reserved"
OUT_OF_SERVICE = "out_of_service"
UNKNOWN = "unknown"
REMOVED = "removed"

# OCPI 2.2.1/2.3.0 EVSE.status
_OCPI = {
    "AVAILABLE": AVAILABLE,
    "CHARGING": OCCUPIED,      # "The EVSE is in use" – auch eingesteckt, aber voll
    "BLOCKED": OCCUPIED,       # Parkplatz blockiert (z.B. Fahrzeug ohne Ladung)
    "RESERVED": RESERVED,
    "OUTOFORDER": OUT_OF_SERVICE,
    "INOPERATIVE": OUT_OF_SERVICE,
    "PLANNED": REMOVED,
    "REMOVED": REMOVED,
    "UNKNOWN": UNKNOWN,
}

# OICP 2.3 EVSEStatus
_OICP = {
    "Available": AVAILABLE,
    "Occupied": OCCUPIED,
    "Reserved": RESERVED,
    "OutOfService": OUT_OF_SERVICE,
    "Unknown": UNKNOWN,
    "EvseNotFound": REMOVED,
}

# Zustände, in denen der Ladepunkt grundsätzlich nutzbar ist (Nenner der Auslastung)
OPERATIONAL = (AVAILABLE, OCCUPIED, RESERVED)


def normalize(raw: str | None, source: str) -> str:
    if not raw:
        return UNKNOWN
    table = _OCPI if source == "ocpi" else _OICP
    return table.get(raw, table.get(raw.upper(), UNKNOWN) if source == "ocpi" else UNKNOWN)
