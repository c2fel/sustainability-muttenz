"""Minimaler HTTP-Client (nur Standardbibliothek) mit gzip und Retries."""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import USER_AGENT

log = logging.getLogger(__name__)


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


def get(url: str, params: dict | None = None, timeout: float = 60.0,
        retries: int = 3, accept: str = "application/json") -> Response:
    """GET mit gzip-Dekompression und exponentiellem Backoff.

    Wiederholt bei Netzwerkfehlern, HTTP 429 (respektiert ``Retry-After``)
    und 5xx. Andere HTTP-Fehler werden sofort als ``urllib.error.HTTPError``
    weitergereicht.
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "Accept-Encoding": "gzip",
        "User-Agent": USER_AGENT,
    })
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                headers = {k.lower(): v for k, v in r.headers.items()}
                status = r.status
            break
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if attempt < retries and (e.code == 429 or e.code >= 500):
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("HTTP %s für %s – neuer Versuch in %.0fs", e.code, url, wait)
                time.sleep(wait)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries:
                log.warning("Netzwerkfehler %s für %s – neuer Versuch in %.0fs", e, url, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise
    # Content-Encoding: gzip, oder Datei liegt als .json gzip-komprimiert auf S3
    if headers.get("content-encoding") == "gzip" or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return Response(status=status, headers=headers, body=body)


def get_json(url: str, params: dict | None = None, timeout: float = 60.0, retries: int = 3):
    return get(url, params=params, timeout=timeout, retries=retries).json()
