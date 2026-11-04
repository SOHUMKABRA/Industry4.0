# Deployment

## Configuration (environment variables, backend)

| Var | Default | Notes |
|---|---|---|
| `TWIN_ENV` | `development` | `production` refuses to start with default/short `SECRET_KEY` or empty `CREDENTIAL_KEY` |
| `DATABASE_URL` | `sqlite:///./data/twin.db` | PostgreSQL: `postgresql+psycopg://user:pass@host:5432/twin` |
| `SECRET_KEY` | dev value | JWT signing key, ≥ 32 random chars |
| `CREDENTIAL_KEY` | empty | Fernet key for device credentials: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back it up.** Losing it makes stored device credentials unrecoverable. |
| `ACCESS_TOKEN_MINUTES` | 480 | |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated. Not needed when the UI is served same-origin via nginx. |
| `SEED_DEMO` | `true` | Set `false` in production |
| `TELEMETRY_ENABLED` | `true` | Runs the in-process telemetry runtime (polls enabled devices) |
| `TELEMETRY_POLL_S` | `1.0` | Device poll interval |
| `TELEMETRY_RETENTION_HOURS` | `6` | History kept in the main DB. Raise it with TimescaleDB |
| `MODEL_STORAGE_DIR` | `./data/models` | Uploaded 3D models. Back this up with the database |
| `MAX_MODEL_MB` | `50` | Upload limit per model |

See `backend/.env.example`.

## Production on this machine (current setup)

| Process | Command | Listens |
|---|---|---|
| Platform (UI + API, one process) | `backend/serve.py` (reads `backend/.env`) | `PLATFORM_LISTEN`, default here `0.0.0.0:8000,0.0.0.0:5173` |
| Lab MQTT broker | `python -m labsim.broker` | `127.0.0.1:1883` |
| Lab field simulator | `python -m labsim.app` | PLC `127.0.0.1:5020`, panel `0.0.0.0:8090` |

* **Single process by design:** the telemetry runtime and control engine keep live state in memory, so don't add uvicorn workers. Scale by running per-site instances or edge gateways.
* `./run-local.sh` starts all three in the foreground.
* `./deploy/install.sh` installs them as **systemd user services** (`twin-platform`, `twin-mqtt`, `twin-labsim`) plus a **daily backup timer** (`twin-backup.timer`, 02:30, keeps 14). It also tries to enable *linger* so they start at boot without a login; if that needs admin rights, run `sudo loginctl enable-linger $USER` once.
  Manage with `systemctl --user status|restart|stop twin-platform`, and read logs with `journalctl --user -u twin-platform -f`.
* **Backups:** `backend/.venv/bin/python deploy/backup.py` writes `backups/twin-<timestamp>.tar.gz` (SQLite online backup + uploaded models). **Also back up `backend/.env`**: without `CREDENTIAL_KEY`, stored device credentials can't be decrypted.
  To restore: stop the platform, extract `twin.db` over `backend/data/twin.db`, restore `models/`, then start again.
* **Firewall:** open 8000 (and 5173 if used) to the VPN only; 8090 only for whoever presents the demo. Keep 1883/5020 closed (they're bound to localhost anyway).
* **Lab vs customer equipment:** to connect real machinery, add devices pointing at the customer's PLCs/broker. For the real plant, disable the lab devices (or set `DEMO_FIELD_DEVICES=false` and `SEED_DEMO=false` for a clean installation).

## Local development

See the README quick start. SQLite with WAL mode is used by default, so there is
no infrastructure to run.

## Docker Compose (PostgreSQL + API + nginx)

```bash
cp backend/.env.example .env   # edit secrets
docker compose up --build      # UI at http://localhost:8080
```

* `web` (nginx) serves the built SPA and proxies `/api` (including WebSocket
  upgrade) to `api`. Security headers are set in `frontend/nginx.conf`.
* `api` runs as a non-root user and has a container healthcheck on `/api/health`.
* `db` is PostgreSQL 16 with a named volume.

> **Not yet verified:** the Compose stack and the PostgreSQL code path were
> written in Phase 1 but haven't been run (no Docker access in the build
> environment). The SQLite path is covered by the test suite. Run the
> stack once and execute the backend tests against PostgreSQL
> (`DATABASE_URL=... pytest`) before relying on it.

## Production checklist (current state)

- [ ] `TWIN_ENV=production`, strong `SECRET_KEY`, `CREDENTIAL_KEY` stored in a secret manager
- [ ] `SEED_DEMO=false`
- [x] Login rate limiting, security headers + CSP, single-origin UI/API
- [x] Daily backups (`deploy/install.sh` timer)
- [ ] TLS: put the platform behind a reverse proxy with a certificate if it is reachable beyond a trusted VPN
- [ ] PostgreSQL backups (`pg_dump` nightly + WAL archiving), with a tested restore
- [x] Additive schema migrations at start-up (`schema_sync.py`)

- [ ] Network: the platform host reaches plant devices only through approved routes or an edge gateway; PLC networks are not routed to user workstations

## Edge deployments (Phase 7 design)

The same backend image runs as an **edge gateway** (`TWIN_ROLE=gateway`) on an
industrial PC inside the OT network, with SQLite for buffering. It connects
*outbound* over mTLS to the central platform, so no inbound firewall openings are
needed into the OT network. Telemetry is store-and-forward with a bounded disk
buffer. Commands are delivered only through the authenticated gateway channel and
re-validated locally.
