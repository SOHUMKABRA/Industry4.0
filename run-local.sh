#!/usr/bin/env bash
# Run the full stack in the foreground (nothing is installed; stops with Ctrl+C):
#   - lab MQTT broker          127.0.0.1:1883   (demo equipment)
#   - lab field simulator      virtual PLC 127.0.0.1:5020, presenter panel 0.0.0.0:8090
#   - platform (UI + API)      0.0.0.0:8000 and 0.0.0.0:5173
# For services that survive logout/reboot use ./deploy/install.sh instead.
#   PLATFORM_LISTEN="127.0.0.1:8000" ./run-local.sh     # this PC only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
B="$ROOT/backend"
export PLATFORM_LISTEN="${PLATFORM_LISTEN:-0.0.0.0:8000,0.0.0.0:5173}"
export LAB_PANEL_HOST="${LAB_PANEL_HOST:-0.0.0.0}"

[ -x "$B/.venv/bin/python" ] || python3 -m venv "$B/.venv"
"$B/.venv/bin/pip" install -q -r "$B/requirements-lab.txt"
( cd "$ROOT/frontend" && { [ -d node_modules ] || npm ci --silent; } && npm run build --silent )

cd "$B"
.venv/bin/python -m labsim.broker & P1=$!
sleep 1.5
.venv/bin/python -m labsim.app & P2=$!
sleep 1
# .env (production secrets) is read by the platform from this directory.
.venv/bin/python serve.py & P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null' EXIT INT TERM

IP=$(hostname -I | awk '{print $1}')
echo
echo "  Platform (UI + API):  http://$IP:8000   (also :5173)   API docs: /api/docs"
echo "  Lab presenter panel:  http://$IP:8090"
echo "  Login: admin@demo.example.com / demo1234   (change passwords in Settings)"
echo
wait
