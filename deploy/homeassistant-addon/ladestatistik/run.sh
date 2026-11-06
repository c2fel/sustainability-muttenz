#!/bin/sh
# Daten liegen im Add-on-Konfigordner (/config = /addon_configs/local_ladestatistik)
set -e
CFG=/config/config.toml
[ -f "$CFG" ] || cp /app/config.example.toml "$CFG"
# Tarife werden direkt in /addon_configs/local_ladestatistik/tarife.toml gepflegt
[ -f /config/tarife.toml ] || cp /app/tarife.toml /config/tarife.toml
mkdir -p /config/data /config/site
cd /app
python3 -m ladestatistik -c "$CFG" serve --host 0.0.0.0 --port 8099 &
( while true; do python3 -m ladestatistik -c "$CFG" publish --days 28 || true; sleep 900; done ) &
exec python3 -m ladestatistik -c "$CFG" collect
