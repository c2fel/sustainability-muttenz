#!/bin/sh
# Daten liegen im Add-on-Konfigordner (/config = /addon_configs/local_ladestatistik)
set -e
CFG=/config/config.toml
[ -f "$CFG" ] || cp /app/config.example.toml "$CFG"
mkdir -p /config/data /config/site
cd /app
python3 -m http.server 8099 --directory /config/site &
( while true; do python3 -m ladestatistik -c "$CFG" publish --days 28 || true; sleep 900; done ) &
exec python3 -m ladestatistik -c "$CFG" collect
