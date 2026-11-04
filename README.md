# Industrial Digital Twin Platform

A configuration-driven platform for building a digital representation of a factory
(floors, areas, machines, sensors), connecting real devices to it, and later
monitoring, simulating and safely controlling them.

**Status: version 1.1. Phases 1–6 are complete.** Real device integration
(Modbus TCP, MQTT), a safe control engine, server-side alerts and notifications,
no-code automations, analytics and reports, historical playback, simulation
scenarios, a 2D/3D twin editor, live monitoring and dashboards. See
[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) for what's left (Phase 7:
edge gateway, OPC UA/S7, PostgreSQL/Timescale, SSO).

**For the client demo, follow [DEMO_GUIDE.md](DEMO_GUIDE.md).**

The demo plant is simulated: some devices are pure software simulators (tagged
`SIM`), and Line 3 plus the MQTT sensors run on the **lab field simulator**, a
separate virtual PLC and transmitters reached over real Modbus TCP and MQTT.

| Doc | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module boundaries, risks, decisions |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Entities, relationships, JSON definition formats |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | REST endpoints, auth, errors |
| [DEVICE_INTEGRATION.md](DEVICE_INTEGRATION.md) | Adapter SDK, writing a protocol adapter |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Running locally, Docker, configuration, production checklist |
| [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) | Phases, status, known gaps |
| [DEMO_GUIDE.md](DEMO_GUIDE.md) | Step-by-step client demo script |

## Stack

* **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2. Uses SQLite by default; set `DATABASE_URL` for PostgreSQL.
* **Frontend:** React 18 + TypeScript + Vite. Plain CSS (dark/light), system fonts, no UI kit. Runtime deps: `react`, `react-dom`, `react-router-dom`, `zustand`, plus `three` / `@react-three/fiber` / `@react-three/drei` for the 3D views (lazy-loaded, so only the editor and monitor pages download them).

## Run everything

```bash
./run-local.sh          # foreground; stops with Ctrl+C or when the terminal session ends
./deploy/install.sh     # systemd user services: survive logout and start at boot (see DEPLOYMENT.md)
```

Either way you get:

| What | Address |
|---|---|
| Platform UI + API (same server) | `http://<host>:8000` (also `:5173`) · API docs `/api/docs` |
| Lab presenter panel (stands in for the physical plant) | `http://<host>:8090` |
| Lab virtual PLC (Modbus TCP) / MQTT broker | `127.0.0.1:5020` / `127.0.0.1:1883` (local only) |

The platform runs in production mode (`TWIN_ENV=production`) with secrets in
`backend/.env`. That file is generated once with random keys; keep it private and back it up.

## Quick start (manual, for development)

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
sensors, energy meters, pump, tank, control panel, PLC), a 51-object 3D layout
(walls, doors, windows, columns, walkways, robot safety zone, racks, benches),
23 simulated devices and a "Plant overview" dashboard. Simulated behaviour includes
a conveyor and its drive cycling running → stopped → running → fault, a robot cycle,
and a shrink-tunnel temperature that periodically crosses its warning/alarm limits.

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

## What you can do today

1. Register an organization (it gets a copy of the standard equipment-type library) or use the demo.
2. Create factories, floors and areas, with lengths entered in mm/cm/m/ft. A 2D plan is drawn from the stored area footprints.
3. Define **asset types** in the UI: custom properties (typed, ranged, enums, defaults), telemetry measurements with warn/alarm limits, control declarations, and default visuals. No code or JSON editing needed.
4. Create, edit, duplicate and delete **assets**. Forms are generated from the asset type, validated on both client and server, and protected by optimistic version checks.
5. Connect **devices** with the onboarding wizard: basics → protocol → connection settings → test → discover and map points → activate. Only the *simulated* protocol is implemented yet; MQTT and Modbus TCP are Phase 3.
6. Every change is recorded in the **audit log**. Device credentials are encrypted at rest and are write-only through the API.
7. **Device integration**: Modbus TCP (coils, discrete inputs, holding/input registers; 16/32-bit, float; byte/word order; value maps) and MQTT (JSON or raw payloads, TLS, credentials). Templates, discovery (register scan or topic sniffing), live health and diagnostics per device.
8. **Control**: start/stop/setpoint commands with permission, limit and interlock checks (fail closed), confirmation, optional four-eyes approval, device acknowledgement, and verification of the result through telemetry. A full lifecycle timeline and audit trail for every command.
9. **Alerts**: limit, equipment-fault, communication-loss and failed-command alerts raised server-side, with on/off delays against chatter, escalation, acknowledgement, a notification bell and live toasts.
10. **Users & security**: user management with roles, temporary passwords with forced change, login rate limiting, security headers/CSP, encrypted device credentials, audit log.
11. **Analytics & reports**: utilization, runtime, downtime and starts per machine; energy (kWh per hour/day); production counts; machine comparison; daily report (printable/PDF and CSV). Hourly roll-ups are kept for 400 days.
12. **Automations**: no-code WHEN/THEN rules on live conditions (AND/OR, held for N s) or schedules, with actions alert / notify / command / wait. Commands go through the full control safety chain. Validation, dry run with what-if values, run history.
13. **Notifications**: webhook (HMAC-signed) and e-mail channels, retries, delivery log; alerts are sent on raise/escalation (optionally on clear).
14. **Historical playback**: replay the plant in the 3D/2D twin at 1–300×, clearly marked; controls are disabled.
15. **Simulation**: fault injection and scripted scenarios on simulated devices only.
16. **Twin editor** (`/editor`): 3D and 2D (top-down plan) views of the *same* objects. Drag unplaced assets, new assets (created from a type) or building elements (walls, doors, windows, columns, zones, walkways, safety zones, workstations, racks) onto the floor. Move/rotate/scale gizmo with grid snap, numeric transform fields in your length unit, multi-select, group, align/distribute, lock, hide, duplicate, full undo/redo, keyboard shortcuts, GLB/OBJ/STL model upload, saved versions with history and restore, conflict detection when two people save, and a built-in performance HUD plus a 5,000-object stress test.
17. **Live monitoring** (`/monitor`): the twin with per-asset status beacons (running, stopped, warning, alarm, fault, stale, no data), animated conveyors, motors and robot driven *only* by fresh "running" state, live tank level, plant KPIs, a filterable equipment list, and per-asset live values with history trends.
18. **Dashboards** (`/dashboards`): configurable widgets (live value, gauge, trend chart, equipment state, plant KPIs, limit violations, data sources); drag to reorder, resize, add/remove, and multiple dashboards per factory.
