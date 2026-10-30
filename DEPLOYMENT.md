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

See `backend/.env.example`.

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
- [ ] TLS terminated at the reverse proxy
- [ ] PostgreSQL backups (`pg_dump` nightly + WAL archiving), with a tested restore
- [ ] Alembic migrations in place. **Gap:** Phase 1 uses `create_all`
- [ ] Login rate limiting. **Gap:** Phase 7
- [ ] Network: the platform host reaches plant devices only through approved routes or an edge gateway; PLC networks are not routed to user workstations

## Edge deployments (Phase 7 design)

The same backend image runs as an **edge gateway** (`TWIN_ROLE=gateway`) on an
industrial PC inside the OT network, with SQLite for buffering. It connects
*outbound* over mTLS to the central platform, so no inbound firewall openings are
needed into the OT network. Telemetry is store-and-forward with a bounded disk
buffer. Commands are delivered only through the authenticated gateway channel and
re-validated locally.
