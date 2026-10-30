# Industrial Digital Twin Platform

A configuration-driven platform for building a digital representation of a factory
(floors, areas, machines, sensors), connecting real devices to it, and later
monitoring, simulating and safely controlling them.

**Status: Phase 1 (platform foundation) complete.** See
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) for what exists and what's next.
No live telemetry or control exists yet. The UI says so wherever it matters and
never shows estimated machine states.

| Doc | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module boundaries, risks, decisions |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Entities, relationships, JSON definition formats |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | REST endpoints, auth, errors |
| [DEVICE_INTEGRATION.md](DEVICE_INTEGRATION.md) | Adapter SDK, writing a protocol adapter |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Running locally, Docker, configuration, production checklist |
| [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) | Phases, status, known gaps |

## Stack

* **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2. Uses SQLite by default; set `DATABASE_URL` for PostgreSQL.
* **Frontend:** React 18 + TypeScript + Vite. Plain CSS (dark/light), system fonts, no UI kit. Runtime deps are `react`, `react-dom` and `react-router-dom` only.

## Quick start (no Docker)

```bash
# Backend: http://localhost:8000 (OpenAPI docs at /docs)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend: http://localhost:5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

On first start the backend seeds the **Riverside Plant** demo: 1 floor, 3 areas,
3 production lines, 23 assets (conveyors, motors, robot arm, temperature/pressure
sensors, energy meters, pump, tank, control panel, PLC) and 9 simulated devices.

| Login | Role |
|---|---|
| `admin@demo.example.com` | admin |
| `engineer@demo.example.com` | engineer (configure everything, no user admin) |
| `operator@demo.example.com` | operator (read + test connections) |
| `viewer@demo.example.com` | viewer (read only) |

Password for all demo users: `demo1234`. Development only: set `SEED_DEMO=false`
in production.

> If `npm run dev` fails with `ENOSPC: System limit for number of file watchers
> reached`, raise the Linux inotify limit
> (`echo fs.inotify.max_user_watches=524288 | sudo tee /etc/sysctl.d/90-inotify.conf && sudo sysctl --system`)
> or use `npm run build && npx vite preview --port 5173`, which also proxies `/api`.

## Tests

```bash
cd backend && .venv/bin/pytest -q      # API, tenancy isolation, permissions, validation, adapters
cd frontend && npm test && npm run typecheck
```

## What you can do today (Phase 1)

1. Register an organization (it gets a copy of the standard equipment-type library) or use the demo.
2. Create factories, floors and areas, with lengths entered in mm/cm/m/ft. A 2D plan is drawn from the stored area footprints.
3. Define **asset types** in the UI: custom properties (typed, ranged, enums, defaults), telemetry measurements with warn/alarm limits, control declarations, and default visuals. No code or JSON editing needed.
4. Create, edit, duplicate and delete **assets**. Forms are generated from the asset type, validated on both client and server, and protected by optimistic version checks.
5. Connect **devices** with the onboarding wizard: basics → protocol → connection settings → test → discover and map points → activate. Only the *simulated* protocol is implemented yet; MQTT and Modbus TCP are Phase 3.
6. Every change is recorded in the **audit log**. Device credentials are encrypted at rest and are write-only through the API.
