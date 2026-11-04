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
| Tests | ✅ | 59 backend (pytest), 24 frontend (vitest) as of v1.1 |
| Docker / Compose / nginx | 🟡 | Written but not run; PostgreSQL path untested |
| Schema migrations | 🟡 | Additive column migrations run automatically at start-up (`schema_sync.py`); destructive changes still need hand-written migrations / Alembic |

## Phase 2: Digital twin editor ✅

| Item | Status | Notes |
|---|---|---|
| Scenes, scene objects, immutable scene versions, restore | ✅ | One layout per factory; save = new version; optimistic `base_version` check (409) |
| Asset identity separate from visuals | ✅ | `SceneObject.asset_id`; deleting an asset removes its visual; removing a visual keeps the asset; one placement per asset |
| R3F canvas, demand rendering, 3D perspective + 2D orthographic on the same objects | ✅ | `frameloop="demand"`; animations request frames only while equipment runs |
| Asset library drag-and-drop (unplaced assets, new assets from types, building elements) | ✅ | Dropping a type creates a real asset record |
| Gizmo move/rotate/scale, snap, numeric fields with unit conversion | ✅ | Multi-select transforms move together |
| Multi-select, group/ungroup, align/distribute, lock, hide, duplicate | ✅ | Asset visuals can't be duplicated (one physical asset) |
| Undo/redo (command pattern) | ✅ | Drag = one step; undo restores list order |
| Keyboard shortcuts | ✅ | W/E/R, Ctrl+Z/Y/D/G/S/A, arrows, L, H, Del, 2/3/F |
| 3D model upload (GLB, OBJ, STL) | ✅ | Validated (type, magic, 50 MB limit), auth-protected download. FBX: convert to GLB. **No server-side mesh optimisation yet** |
| Instancing | ✅ | Walls, doors, windows, columns, racks, benches, boxes are GPU-instanced |
| Performance HUD + 5,000-object stress test | ✅ | 5,051 objects → 193 draw calls. FPS not yet benchmarked on real GPU hardware |
| LOD, frustum-based lazy loading per area, Draco/meshopt compression | ⏳ | Needed for very large plants / heavy CAD models |
| Multiple floors in the editor | 🟡 | Data model supports `floor_id`; the editor shows the first floor |

## Phase 3: Device integration ✅

| Item | Status | Notes |
|---|---|---|
| Modbus TCP adapter | ✅ | pymodbus client; co/di/hr/ir; uint16/int16/uint32/int32/float32; byte & word order; integer→text maps; block reads; persistent connection with reconnect; register-scan discovery; coil/register writes |
| MQTT adapter (push) | ✅ | aiomqtt; JSON paths or raw payloads; device `ts`/`seq` honoured; TLS + credentials (encrypted); reconnect with backoff; topic discovery by sniffing; command publish |
| Push + poll runtime | ✅ | Push adapters stream into the same ingest pipeline |
| Plugin loading | ✅ | `twin.adapters` entry points |
| Device templates | ✅ | Built-in templates per organization, applied in the onboarding wizard; API to add your own |
| Device health / diagnostics | ✅ | Online/offline, samples, errors, poll round-trip, adapter diagnostics; communication-loss alerts |
| Lab field simulator | ✅ | `backend/labsim`: virtual PLC (own Modbus TCP server, PLC logic, E-stop, faults), MQTT transmitters, presenter panel |
| OPC UA, S7, EtherNet/IP, BACnet, Modbus RTU | ⏳ | Same adapter interface; serial/fieldbus need an edge gateway |

## Phase 4: Live digital twin 🟡 (core working, on simulated devices)

| Item | Status | Notes |
|---|---|---|
| In-process telemetry runtime polling enabled, asset-bound devices | ✅ | `app/telemetry/runtime.py`; same class can later run in an edge gateway |
| Point mapping (scale/offset), duplicate (device, seq) and out-of-order filtering | ✅ | Tested |
| Latest-value cache, batched history writes, retention pruning | ✅ | Failed writes are re-queued, not dropped. Default retention 6 h (`TELEMETRY_RETENTION_HOURS`) |
| WebSocket stream: single-use ticket auth, per-factory subscription, coalescing (≤4 Hz/key), heartbeat, latency ping | ✅ | Tenant isolation tested |
| Frontend telemetry store outside React, rAF-batched, per-key subscriptions | ✅ | 3D reads values directly in the render loop |
| Stale/offline detection and data-source marking (`SIM`) | ✅ | Never shows "running" from stale data (tested) |
| History API with downsampling + trend charts | ✅ | Python bucketing; Timescale `time_bucket` on PostgreSQL is still to do |
| Simulated data generators (13 profiles) | ✅ | |
| Real device data (MQTT/Modbus) | ⏳ | Phase 3 |
| Historical playback mode | ⏳ | |
| Load test (5k points/s, 50 clients) | ⏳ | Not yet measured |

## Phase 5: Control engine ✅

| Item | Status | Notes |
|---|---|---|
| Lifecycle REQUESTED → … → COMPLETED / REJECTED / FAILED / TIMED_OUT / CANCELLED | ✅ | Every transition timestamped, pushed live and audited |
| Validation chain | ✅ | Permission + per-control minimum role, capability, parameter limits, device online and write-capable, interlocks, concurrency, rate limits, confirmation |
| Interlocks | ✅ | Per asset/control, on any measurement of any asset in the factory; stale or missing data blocks (fail closed); re-checked right before sending |
| Four-eyes approval | ✅ | Per control; requester can't approve; engineer/admin approve or reject with reason; cancel |
| Acknowledgement + verification | ✅ | Device ack required; COMPLETED·verified only when the expected feedback is seen in fresh telemetry, else TIMED_OUT "state unverified" |
| Restart safety | ✅ | In-flight commands are marked FAILED "state unknown" on start-up |
| Simulated vs real | ✅ | Commands carry `simulated`; simulated devices only change simulator state |
| Software E-stop | ❌ by design | E-stop status is monitored and used in interlocks; stopping the plant safely is the job of hardwired circuits |

## Phase 6: Analytics, automation & simulation ✅

| Item | Status | Notes |
|---|---|---|
| Configurable dashboards | ✅ | 7 widget types, drag-reorder, sizes |
| Server-side alerts | ✅ | Limit / equipment fault / comm loss / failed command / automation; on-delay 3 s, off-delay 10 s, 2 % deadband; escalation; acknowledgement |
| Notifications | ✅ | Webhook (HMAC-SHA256 `X-Twin-Signature`), e-mail (SMTP/STARTTLS); queue + 3 retries; delivery log; notify on raise / escalation / optional clear |
| Hourly roll-ups (long-term history) | ✅ | 400 days; late-arriving data re-rolled; state time + starts; first/last for counters |
| Analytics | ✅ | Utilization/runtime/downtime/starts, energy kWh, production, machine comparison (raw ≤24 h, hourly beyond) |
| Reports | ✅ | Daily operations report: printable (PDF via browser) and CSV |
| No-code automation engine | ✅ | Condition (AND/OR, held-for) and schedule triggers; alert/notify/command/delay actions; edge-triggered + cooldown; stale data = false; commands via control engine as the rule owner (approval-required controls wait for a person); validation, dry run with what-if values, execution history, audit |
| Historical playback | ✅ | 15 min – 24 h windows, 1–300×, scrubbing; live data paused; REPLAY tags; controls disabled |
| Simulation scenarios | ✅ | Quick injection (force value / offline / restore) and scripted scenarios; simulated devices only (enforced server-side) |
| Visual flow-graph editor | 🟡 | Rules are built in a structured WHEN/THEN form (no code); a node-graph canvas isn't built |
| SMS / Teams / Slack channels | ⏳ | Use a webhook into those services for now |
| Alarm shelving, alarm KPIs (ISA-18.2 rates) | ⏳ | |

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
* E-mail delivery is implemented and unit-tested but not exercised against a real SMTP server here (no mail server on this machine).
* The lab MQTT broker is unauthenticated and bound to localhost. For the customer's plant, use Mosquitto/EMQX with TLS and credentials.
* SQLite is fine for a single site with this load; move to PostgreSQL + TimescaleDB for larger plants or longer retention.
* Telemetry history lives in the main database. Fine for SQLite/single site; use TimescaleDB for production volumes.
* The editor keeps unsaved changes in memory across page navigation, but closing the tab loses them (the browser warns first).
