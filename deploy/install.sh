#!/usr/bin/env bash
# Install / update the platform as systemd *user* services on this machine.
#   ./deploy/install.sh            build + (re)start everything
# Services: twin-platform (UI+API), twin-mqtt (lab broker), twin-labsim (lab field simulator),
#           twin-backup.timer (daily backup at 02:30).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="$ROOT/backend"
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS" "$ROOT/backups" "$B/data"

echo "==> Python environment"
[ -x "$B/.venv/bin/python" ] || python3 -m venv "$B/.venv"
"$B/.venv/bin/pip" install -q -r "$B/requirements-lab.txt"

echo "==> Production configuration"
if [ ! -f "$B/.env" ]; then
  SECRET=$("$B/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
  CRED=$("$B/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  cat > "$B/.env" <<ENV
TWIN_ENV=production
DATABASE_URL=sqlite:///$B/data/twin.db
SECRET_KEY=$SECRET
# Back this key up with the database: without it stored device credentials can't be decrypted.
CREDENTIAL_KEY=$CRED
SEED_DEMO=true
DEMO_FIELD_DEVICES=true
TELEMETRY_RETENTION_HOURS=24
MODEL_STORAGE_DIR=$B/data/models
CORS_ORIGINS=
ENV
  chmod 600 "$B/.env"
  echo "    wrote $B/.env (new secrets)"
fi

echo "==> Frontend build"
( cd "$ROOT/frontend" && { [ -d node_modules ] || npm ci --silent; } && npm run build --silent )

echo "==> systemd units"
cat > "$UNITS/twin-mqtt.service" <<UNIT
[Unit]
Description=Twin lab MQTT broker (demo equipment)
After=network-online.target

[Service]
WorkingDirectory=$B
Environment=MQTT_BIND=127.0.0.1:1883
ExecStart=$B/.venv/bin/python -m labsim.broker
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
cat > "$UNITS/twin-labsim.service" <<UNIT
[Unit]
Description=Twin lab field simulator (virtual PLC + MQTT transmitters, demo equipment)
After=twin-mqtt.service
Wants=twin-mqtt.service

[Service]
WorkingDirectory=$B
Environment=LAB_PANEL_HOST=0.0.0.0 LAB_PANEL_PORT=8090 LAB_MODBUS_HOST=127.0.0.1 LAB_MODBUS_PORT=5020 LAB_MQTT_HOST=127.0.0.1 LAB_MQTT_PORT=1883
ExecStart=$B/.venv/bin/python -m labsim.app
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
cat > "$UNITS/twin-platform.service" <<UNIT
[Unit]
Description=Industrial Digital Twin Platform (UI + API)
After=network-online.target twin-labsim.service

[Service]
WorkingDirectory=$B
EnvironmentFile=$B/.env
Environment=PLATFORM_LISTEN=0.0.0.0:8000,0.0.0.0:5173
ExecStart=$B/.venv/bin/python serve.py
Restart=always
RestartSec=3
TimeoutStopSec=20
NoNewPrivileges=yes

[Install]
WantedBy=default.target
UNIT
cat > "$UNITS/twin-backup.service" <<UNIT
[Unit]
Description=Twin platform backup

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$B/.venv/bin/python $ROOT/deploy/backup.py
UNIT
cat > "$UNITS/twin-backup.timer" <<UNIT
[Unit]
Description=Daily twin platform backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now twin-mqtt.service twin-labsim.service twin-platform.service twin-backup.timer >/dev/null
systemctl --user restart twin-mqtt.service twin-labsim.service twin-platform.service
loginctl enable-linger "$USER" 2>/dev/null && echo "==> linger enabled: services run without an active login and start at boot" \
  || echo "!!  Could not enable linger. Run once:  sudo loginctl enable-linger $USER   (so services start at boot without login)"
echo "==> Done. UI/API: http://$(hostname -I | awk '{print $1}'):8000  (also :5173)   Lab panel: :8090"
