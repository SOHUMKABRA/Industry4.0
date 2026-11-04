# API documentation

Base path `/api`. JSON in and out. Interactive OpenAPI docs are served at
`http://<host>:8000/api/docs` and are always current. This file
summarises the API and its conventions.

## Authentication

`POST /api/auth/login {email, password}` → `{access_token, token_type, me}`.
Send `Authorization: Bearer <token>` on every other call. Tokens are HS256 JWTs and
expire after 8 h (`ACCESS_TOKEN_MINUTES`).

`me = {user, organization, permissions[]}`. The UI hides actions the user lacks,
and the server enforces them again regardless.

| Permission | admin | engineer | operator | viewer |
|---|:-:|:-:|:-:|:-:|
| read | ✓ | ✓ | ✓ | ✓ |
| device.test | ✓ | ✓ | ✓ | |
| factory.write, asset.write, asset_type.write, device.write, audit.read | ✓ | ✓ | | |
| control.execute, alert.ack | ✓ | ✓ | ✓ | |
| control.approve | ✓ | ✓ | | |
| user.manage (incl. delete factory) | ✓ | | | |

## Conventions

* **Tenancy:** ids belonging to another organization return **404**, never 403.
* **Errors:** `{"detail": ...}`. `detail` is a string, a FastAPI validation list
  (`[{loc, msg}]`), or `{message, fields: {key: msg}}` for asset property errors
  and `{message, assets: [...]}` for blocked type changes.
* **Status codes:** 401 unauthenticated · 403 missing permission · 404 not found / other tenant · 409 conflict (duplicate key, stale version, in use) · 422 validation.
* **Concurrency:** `PATCH /assets/{id}` accepts `version`; a mismatch returns 409.
* **Audit:** every mutation writes an audit row in the same transaction.

## Endpoints

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `{organization_name, name, email, password, install_standard_library=true}`. Creates the org; the caller becomes admin |
| POST | `/auth/login` | |
| GET | `/auth/me` | |

### Factories, floors, areas
| Method | Path | Perm |
|---|---|---|
| GET | `/factories` | read |
| POST | `/factories` | factory.write |
| GET | `/factories/{id}` | read: factory with nested `floors[].areas[]` |
| PATCH | `/factories/{id}` | factory.write |
| DELETE | `/factories/{id}` | user.manage |
| GET | `/factories/{id}/summary` | read: counts by category/area, device test state |
| POST | `/factories/{id}/floors` | factory.write |
| PATCH / DELETE | `/floors/{id}` | factory.write |
| POST | `/floors/{id}/areas` | factory.write: `{name, kind, bounds:{x,z,width,depth}}` (metres) |
| PATCH / DELETE | `/areas/{id}` | factory.write (DELETE 409 if the area holds assets) |

### Asset types
| Method | Path | Perm |
|---|---|---|
| GET | `/asset-types?category=` | read: includes `asset_count` |
| GET | `/asset-types/{id}` | read |
| POST | `/asset-types` | asset_type.write (see DATABASE_SCHEMA.md for definition formats) |
| PATCH | `/asset-types/{id}` | asset_type.write: bumps `version`, re-validates existing assets |
| DELETE | `/asset-types/{id}` | asset_type.write (409 if in use) |

### Assets
| Method | Path | Perm |
|---|---|---|
| GET | `/assets?factory_id=&area_id=&asset_type_id=&category=&parent_id=&q=&limit=&offset=` | read (`area_id=unassigned` supported) |
| GET | `/assets/{id}` | read |
| POST | `/assets` | asset.write: `{factory_id, asset_type_id, code, name, area_id?, parent_id?, properties, ...}` |
| PATCH | `/assets/{id}` | asset.write: partial, optional `version` |
| DELETE | `/assets/{id}` | asset.write: snapshot kept in audit log |

Server checks: area belongs to the same factory, parent is in the same factory with
no cycle, `code` is unique per org, and properties are validated against the type.

### Devices
| Method | Path | Perm |
|---|---|---|
| GET | `/protocols` | read: available adapters with `config_schema`, plus planned ones |
| GET | `/devices?factory_id=&asset_id=` | read |
| GET | `/devices/{id}` | read: `has_credentials` boolean; credentials are never returned |
| POST | `/devices` | device.write: `{factory_id, name, protocol, asset_id?, connection_config, credentials?, point_mappings[], enabled}` |
| PATCH | `/devices/{id}` | device.write: changing connection settings resets the test status |
| DELETE | `/devices/{id}` | device.write |
| POST | `/devices/{id}/test` | device.test: `{ok, message, latency_ms}`, 10 s timeout, result stored |
| POST | `/devices/{id}/discover` | device.test: `[{point, label, data_type, unit, suggested_measurement}]` |

Point mappings must target measurements defined on the bound asset's type.

### Audit / health
| Method | Path | Perm |
|---|---|---|
| GET | `/audit?entity_id=&entity_type=&limit=` | audit.read |
| GET | `/health` | none (checks database connectivity) |

### Scenes (layouts)
| Method | Path | Perm |
|---|---|---|
| GET | `/factories/{id}/scene` | read: `{scene, objects[]}`, created empty if missing |
| PUT | `/scenes/{id}` | factory.write: `{base_version, message, objects[]}` replaces all objects and writes version N+1. Stale `base_version` → 409 |
| GET | `/scenes/{id}/versions` | read: newest first (no snapshots) |
| POST | `/scenes/{id}/versions/{v}/restore` | factory.write: restores as a new version; objects for deleted assets are skipped |

Scene object: `{id (uuid), kind (asset|wall|door|window|pillar|zone|walkway|safety_zone|workstation|storage|label|box), asset_id?, name, shape, position[3], rotation[3] (radians), scale[3], size[3] (m), color, opacity, model_id?, floor_id?, group_id?, locked, hidden, sort, props}`. `position` is the centre of the object's **base**. Server checks: asset objects reference an asset in the same factory, each asset is placed at most once, non-asset objects have no asset, and model ids belong to the org.

### 3D models
| Method | Path | Perm |
|---|---|---|
| GET | `/models` | read |
| POST | `/models` (multipart `file`) | factory.write: `.glb`, `.obj`, `.stl`, ≤ `MAX_MODEL_MB`; content-sniffed |
| GET | `/models/{id}/file` | read (Bearer auth; the 3D loaders send it) |
| DELETE | `/models/{id}` | factory.write (409 if used in a layout) |

### Live telemetry
| Method | Path | Perm |
|---|---|---|
| POST | `/live/ticket` | read: `{ticket, expires_in: 30}`, single use |
| GET | `/live/snapshot?factory_id=` | read: `{points[], devices[], running}` |
| GET | `/assets/{id}/history?measurement=&minutes=60&buckets=120` | read: `{from, to, points:[{t, avg, min, max, last, count, source}]}` |
| WS | `/live/ws?ticket=` | see below |

WebSocket protocol:
* client → `{"type":"subscribe","factory_id":"…","asset_ids":[…]?}`; server → `{"type":"snapshot", points, devices, running}`
* server → `{"type":"telemetry","points":[[asset_id, measurement, value, ts_ms, quality, source], …]}`, coalesced so each key appears at most once per 250 ms
* server → `{"type":"heartbeat","server_ts", devices:[{device_id, asset_id, online, source, last_seen, error}], running}` every ~2 s
* client → `{"type":"ping","t":…}`; server → `{"type":"pong","t":…}`
* Invalid or expired ticket: the socket closes with code 4401. Subscribing to another org's factory returns `{"type":"error"}`.

### Dashboards
| Method | Path | Perm |
|---|---|---|
| GET | `/dashboards?factory_id=` | read |
| POST | `/dashboards` | read (anyone can create): `{factory_id, name, widgets[]}` |
| PATCH / DELETE | `/dashboards/{id}` | the author, or factory.write |

Widget: `{id, type (value|gauge|trend|state|kpis|alarms|devices), title, size (s|m|l|w), asset_id?, measurement?, minutes}`. Widget assets must belong to the dashboard's factory.

### Users
| Method | Path | Perm |
|---|---|---|
| GET / POST | `/users` | user.manage. POST `{email, name, role, password?}`; without a password a temporary one is returned once and must be changed at first login |
| PATCH | `/users/{id}` | user.manage: `{name?, role?, is_active?}`; the last active admin is protected |
| POST | `/users/{id}/reset-password` | user.manage: returns a temporary password |
| POST | `/auth/change-password` | self: `{current_password, new_password}` |

Login is rate limited: 8 failures per (IP, email) or 30 per IP within 10 min → 429.

### Device templates & diagnostics
| Method | Path | Perm |
|---|---|---|
| GET | `/device-templates` | read |
| POST / DELETE | `/device-templates[/{id}]` | device.write (built-ins can't be deleted) |
| GET | `/devices/{id}/diagnostics` | read: `{active, online, connected, samples, errors, last_error, poll_ms, last_seen, adapter}` |

Devices accept `control_mappings: [{control, point, value?, param?, scale}]` and `template_id`.

### Control
| Method | Path | Perm |
|---|---|---|
| POST | `/assets/{id}/commands/validate` | read: dry run `{ok, checks[], simulated, requires_approval}`; nothing is sent |
| POST | `/assets/{id}/commands` | control.execute (+ the control's `min_role`): `{control, params, confirm, reason}` → command |
| GET | `/commands?factory_id=&asset_id=&status=A,B&limit=` | read |
| GET | `/commands/{id}` | read |
| POST | `/commands/{id}/approve` | control.approve, not the requester |
| POST | `/commands/{id}/reject` | control.approve: `{reason}` |
| POST | `/commands/{id}/cancel` | requester or approver, before sending |

Command: `{id, asset_id, device_id, control_key, control_label, params, status, simulated, verified, reason, requested_by, requested_at, approved_by, sent_at, acked_at, finished_at, result_message, checks[], events[]}`.
Statuses: `REQUESTED, VALIDATING, PENDING_APPROVAL, APPROVED, SENT, ACKNOWLEDGED, COMPLETED, REJECTED, FAILED, TIMED_OUT, CANCELLED`.

### Interlocks
| Method | Path | Perm |
|---|---|---|
| GET / POST | `/assets/{id}/interlocks` | read / factory.write: `{control_key ('*' = all), source_asset_id, measurement, operator (== != < <= > >=), value, message, enabled}` |
| PUT / DELETE | `/interlocks/{id}` | factory.write |

### Alerts
| Method | Path | Perm |
|---|---|---|
| GET | `/alerts?factory_id=&state=active\|history\|all` | read |
| POST | `/alerts/{id}/ack` | alert.ack |
| POST | `/alerts/ack-all?factory_id=` | alert.ack |

WebSocket events (in addition to telemetry): `{"type":"alert","alert":{…}}` and `{"type":"command","command":{…}}`.

### Operations
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, database, telemetry, control, version}` |
| GET | `/metrics` | Prometheus text; served to localhost only |

### Analytics & reports
| Method | Path | Notes |
|---|---|---|
| GET | `/analytics/utilization?factory_id=&hours=` | Per asset: seconds per state, running/downtime/no-data, utilization, starts |
| GET | `/analytics/energy?factory_id=&hours=&bucket=hour\|day` | kWh per bucket per meter |
| GET | `/analytics/production?factory_id=&hours=&bucket=` | Counter increases (item/output/cycle counts) per bucket |
| GET | `/analytics/compare?factory_id=&measurement=&asset_ids=a,b&hours=` | Averages per asset (1–5 min ≤24 h, hourly beyond) |
| GET | `/reports/daily?factory_id=&date=YYYY-MM-DD` · `/reports/daily.csv` | Daily report (factory local day) |
| GET | `/factories/{id}/playback?from_ms=&to_ms=&step_s=` | Recorded series for replay (window ≤24 h) |

### Automations (factory.write to change)
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/automations[?factory_id=]` | Rule: `{factory_id, name, description, enabled, trigger{type, every_minutes?, daily_at?, days}, conditions{match, for_s, items[{asset_id, measurement, operator, value}]}, actions[{type: alert\|notify\|command\|delay, …}], cooldown_s}`. Returns `warnings[]` |
| POST | `/automations/validate` | Validate without saving |
| PUT / DELETE | `/automations/{id}` | The last editor becomes the rule owner (whose permissions commands use) |
| POST | `/automations/{id}/enabled?enabled=true\|false` | |
| POST | `/automations/{id}/dry-run` | `{overrides: {"asset_id:measurement": value}}`; nothing is sent |
| GET | `/automations/{id}/executions` | Run history with per-step results |

### Notification channels (factory.write to change)
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/notification-channels` | `{name, type: webhook\|email, url \| host/port/starttls/username/from_addr/to, secret?/password? (write-only), enabled, alerts, min_severity, notify_clear}` |
| PUT / DELETE | `/notification-channels/{id}` | |
| POST | `/notification-channels/{id}/test` | Sends synchronously; returns status |
| GET | `/notification-channels/{id}/deliveries` | Last 100 attempts |

Webhook body: `{"event": "alert.raised|alert.escalated|alert.cleared|automation|test", "subject", "severity", "sent_at", …}` with header `X-Twin-Signature: sha256=<HMAC-SHA256(secret, body)>`.

### Simulation (simulated devices only)
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/simulation/scenarios[?factory_id=]` | `{factory_id, name, description, steps[{at_s, device_id, action: set\|offline\|restore, point?, value?, duration_s}]}` |
| PUT / DELETE | `/simulation/scenarios/{id}` | |
| POST | `/simulation/scenarios/{id}/run` · `/simulation/stop?factory_id=` · GET `/simulation/status?factory_id=` | One scenario per factory at a time; stopping restores devices |
| POST | `/simulation/inject` | `{device_id, action, point?, value?, duration_s}` |
