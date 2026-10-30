# Implementation roadmap

Status legend: ✅ done and tested · 🟡 partial · ⏳ not started

## Phase 1: Platform foundation ✅

| Item | Status | Notes |
|---|---|---|
| Repo structure, FastAPI app, React shell | ✅ | `backend/`, `frontend/` |
| Auth (register/login/JWT), roles → permissions | ✅ | Fixed roles; custom roles are Phase 7 |
| Multi-tenant data isolation | ✅ | `org_id` on all rows; `get_owned()` returns 404 across tenants; tested |
| Factories, floors, areas (with unit conversion) | ✅ | Lengths stored in metres; mm/cm/m/ft display |
| Metadata-driven asset types (properties, telemetry, controls, visual) | ✅ | Editable in the UI; standard library copied per org from `standard_types.json` |
| Assets with validated custom properties, hierarchy, optimistic versioning | ✅ | Cycle and cross-factory checks |
| Devices: adapter interface, registry, simulated adapter, encrypted write-only credentials | ✅ | |
| Device onboarding wizard (basics → protocol → config → test → discover/map → activate) | ✅ | "Validate incoming data" needs Phase 4 |
| Audit log | ✅ | Every mutation |
| Demo factory | ✅ | 23 assets, 9 simulated devices |
| Tests | ✅ | 25 backend (pytest), 9 frontend (vitest) |
| Docker / Compose / nginx | 🟡 | Written but not run; PostgreSQL path untested |
| Alembic migrations | ⏳ | Required before the first production deployment |

## Phase 2: Digital twin editor ⏳

R3F canvas with `frameloop="demand"`; orthographic 2D / perspective 3D on the same
`SceneObject` records; asset library drag-and-drop from asset types; transform
gizmos (move/rotate/scale) with grid snap; multi-select, group, lock, hide; a
command-pattern undo/redo stack; properties panel reusing `DynamicForm`;
`scenes` / `scene_objects` / immutable `scene_versions` with restore; GLB upload
with server-side validation and meshopt compression; instancing for repeated
shapes; a perf HUD; and a synthetic 5,000-object benchmark scene.
**Exit criterion:** build and save the demo factory in 3D without devices.

## Phase 3: Device integration ⏳

MQTT adapter (aiomqtt), Modbus TCP adapter (pymodbus), entry-point plugin loading,
device templates (register maps / topic maps reusable across devices), adapter
runtime (connection supervisor with backoff), device health/diagnostics.
Integration tests against a Mosquitto container and a pymodbus test server.

## Phase 4: Live digital twin ⏳

Ingestion pipeline (validate → map → dedupe by (device, seq) → order), a latest-value
cache, batched history writes (Timescale hypertable on PostgreSQL), a WebSocket hub
with per-client subscriptions, coalescing and backpressure, stale/offline
detection from `expected_interval_s`, and a frontend telemetry store outside React
(`useSyncExternalStore`, rAF flush). Simulator sessions feed the same pipeline
tagged `source=simulated`. Load test: 5k points/s, 50 clients.

## Phase 5: Control engine ⏳

Command lifecycle state machine, the validation chain (permission → capability → range
→ interlocks on fresh telemetry → rate limit → confirmation → optional approval),
acknowledgement + telemetry verification, timeouts, and full audit. Simulated
devices only until a controlled test rig is available.

## Phase 6: Analytics & automation ⏳

Alerts from telemetry limits, history charts, configurable dashboards, a no-code
rule engine (visual flow, dry-run, no arbitrary code; actions go through the Phase 5
command engine), notifications, simulation scenarios, historical playback.

## Phase 7: Enterprise readiness ⏳

Custom roles and per-asset grants, edge gateway (store-and-forward, mTLS),
backup/restore tooling, observability (Prometheus metrics, structured JSON logs,
OpenTelemetry traces), login rate limiting and session revocation, config
export/import, deployment automation.

## Known gaps / risks carried forward

* No migrations yet (see Phase 1 table).
* JWT in `localStorage`: simple, but readable by any XSS. Mitigations: strict CSP
  via nginx and no `dangerouslySetInnerHTML`; consider httpOnly cookie sessions
  in Phase 7.
* Asset list loads up to 5,000 rows client-side; server-side paging and
  virtualisation are needed for very large plants.
* Control declarations can be edited but not executed. This is intentional until Phase 5.
