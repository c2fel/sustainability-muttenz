"""Statischer Webserver für den Web-Root (z.B. stats.jumut.ch).

* liefert ``out_dir`` aus: ``/`` (Übersicht), ``/reports/charging/`` (Dashboard + Daten)
* keine Verzeichnislisten, nur GET/HEAD
* Cache-Control: HTML nie cachen, JSON/CSV 5 min (Cloudflare cacht CSV sonst bis 2 h)
* Sicherheits-Header (nosniff, CSP, kein Framing)

Ein späteres ``/api/*`` wird im Cloudflare-Tunnel per Pfadregel auf einen eigenen
Dienst geleitet (siehe docs/deployment.md); dieser Server antwortet dort mit 404.
"""

from __future__ import annotations

import logging
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Handler(SimpleHTTPRequestHandler):
    server_version = "ladestatistik"
    sys_version = ""
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }

    def list_directory(self, path):  # keine Verzeichnislisten
        self.send_error(404, "Not Found")
        return None

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

    def _cache_control(self) -> str:
        if getattr(self, "_status", 200) >= 400:
            return "no-store"
        path = self.path.split("?", 1)[0]
        if path.endswith((".json", ".csv")):
            return "public, max-age=300"
        if path.endswith("/") or path.endswith(".html"):
            return "no-cache"
        return "public, max-age=3600"

    def end_headers(self):
        self.send_header("Cache-Control", self._cache_control())
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)


def make_server(directory: Path, host: str = "127.0.0.1", port: int = 8099) -> ThreadingHTTPServer:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer((host, port), partial(Handler, directory=str(directory)))


def serve(directory: Path, host: str = "127.0.0.1", port: int = 8099) -> None:
    httpd = make_server(directory, host, port)
    log.info("Webserver: http://%s:%d/ -> %s", host, port, directory)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
