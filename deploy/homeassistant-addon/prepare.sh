#!/bin/sh
# Kopiert Python-Paket + Beispielkonfiguration in den Add-on-Build-Kontext.
# Danach den Ordner deploy/homeassistant-addon/ladestatistik nach /addons/ auf
# Home Assistant kopieren (Samba- oder SSH-Add-on).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
rm -rf "$HERE/ladestatistik/ladestatistik"
cp -r "$ROOT/ladestatistik" "$HERE/ladestatistik/ladestatistik"
find "$HERE/ladestatistik/ladestatistik" -name __pycache__ -prune -exec rm -rf {} +
cp "$ROOT/config.example.toml" "$HERE/ladestatistik/config.example.toml"
echo "Build-Kontext bereit: $HERE/ladestatistik"
