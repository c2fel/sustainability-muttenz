#!/usr/bin/env python3
"""Supervisor für das Home-Assistant-Add-on "Ladestatistik Muttenz".

Holt den Code von GitHub (öffentliches Repo, kein Schlüssel nötig), startet die Dienste
und rollt neue Commits automatisch aus:

  alle poll_seconds: git fetch -> neuer Stand? -> Unit-Tests + Probe-Publish
                     -> ok: Dienste neu starten | Fehler: zurück auf alten Stand

Dienste: Collector (Dauerbetrieb), Webserver 0.0.0.0:8099, Publish alle 15 min,
Preis-Check täglich. Ausgabe im Add-on-Log.

Pfade: Code in /data/app (Add-on-Daten), Konfiguration und Datenbank in /config
(= /addon_configs/local_ladestatistik). Für Tests über Umgebungsvariablen änderbar.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(os.environ.get("ADDON_DATA", "/data"))
CONF = Path(os.environ.get("ADDON_CONFIG", "/config"))
APP = DATA / "app"
CFG = CONF / "config.toml"
PUBLISH_EVERY = 15 * 60
TARIFFCHECK_EVERY = 24 * 3600

opts = {"repository": "https://github.com/c2fel/sustainability-muttenz.git",
        "branch": "main", "poll_seconds": 120}
if (DATA / "options.json").exists():
    opts.update(json.loads((DATA / "options.json").read_text()))
POLL = max(30, int(opts["poll_seconds"]))
BRANCH = opts["branch"]

procs: dict[str, subprocess.Popen] = {}
stop = False


def log(msg: str) -> None:
    print(f"[ladestatistik] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(APP), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def run(*args: str, timeout: int = 600) -> bool:
    r = subprocess.run([sys.executable, *args], cwd=APP, capture_output=True, text=True,
                       timeout=timeout)
    out = (r.stdout + r.stderr).strip().splitlines()
    for line in out[-5:]:
        log(f"  {line}")
    return r.returncode == 0


def ensure_checkout() -> None:
    while not (APP / ".git").exists() and not stop:
        log(f"klone {opts['repository']} ({BRANCH})")
        r = subprocess.run(["git", "clone", "--branch", BRANCH, opts["repository"], str(APP)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(f"Klonen fehlgeschlagen: {r.stderr.strip()} – neuer Versuch in 60 s")
            time.sleep(60)


def ensure_config() -> None:
    (CONF / "data").mkdir(parents=True, exist_ok=True)
    (CONF / "site").mkdir(parents=True, exist_ok=True)
    if not CFG.exists():
        text = (APP / "config.example.toml").read_text(encoding="utf-8")
        # Tarife aus dem Repo verwenden -> Änderungen an tarife.toml auf GitHub kommen automatisch an
        text = text.replace('manual_file = "tarife.toml"', f'manual_file = "{APP / "tarife.toml"}"')
        CFG.write_text(text, encoding="utf-8")
        log(f"{CFG} aus dem Beispiel erzeugt")


def start_services() -> None:
    base = [sys.executable, "-m", "ladestatistik", "-c", str(CFG)]
    for name, args in (("collect", ["collect"]),
                       ("serve", ["serve", "--host", "0.0.0.0", "--port", "8099"])):
        procs[name] = subprocess.Popen(base + args, cwd=APP)
    log(f"Dienste gestartet (Stand {git('rev-parse', '--short', 'HEAD')})")


def stop_services() -> None:
    for p in procs.values():
        if p.poll() is None:
            p.terminate()
    for p in procs.values():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
    procs.clear()


def publish() -> bool:
    return run("-m", "ladestatistik", "-c", str(CFG), "publish", "--days", "28")


def update(failed: set[str]) -> None:
    git("fetch", "--quiet", "origin", BRANCH)
    old, new = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
    if old == new or new in failed:
        return
    log(f"neuer Stand {new[:7]} (bisher {old[:7]})")
    git("checkout", "--quiet", "--force", "-B", BRANCH, new)
    if run("-m", "unittest", "discover", "-s", "tests", "-q") and publish():
        stop_services()
        start_services()
        log(f"deployt: {new[:7]} – {git('log', '-1', '--format=%s')}")
    else:
        log(f"Prüfung fehlgeschlagen – zurück auf {old[:7]}")
        git("checkout", "--quiet", "--force", "-B", BRANCH, old)
        failed.add(new)


def main() -> None:
    def on_signal(*_):
        global stop
        stop = True
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    ensure_checkout()
    if stop:
        return
    ensure_config()
    start_services()
    failed: set[str] = set()
    next_poll = next_publish = time.time() + 5
    next_check = time.time() + 3600
    while not stop:
        now = time.time()
        for name, p in list(procs.items()):
            if p.poll() is not None:
                log(f"{name} beendet (Code {p.returncode}) – Neustart in 10 s")
                time.sleep(10)
                stop_services()
                start_services()
                break
        if now >= next_poll:
            try:
                update(failed)
            except Exception as exc:  # noqa: BLE001 - Netzfehler etc.
                log(f"Update-Prüfung fehlgeschlagen: {exc}")
            next_poll = now + POLL
        if now >= next_publish:
            publish()
            next_publish = now + PUBLISH_EVERY
        if now >= next_check:
            run("-m", "ladestatistik", "-c", str(CFG), "tariff-check")
            next_check = now + TARIFFCHECK_EVERY
        time.sleep(1)
    stop_services()
    log("beendet")


if __name__ == "__main__":
    main()
