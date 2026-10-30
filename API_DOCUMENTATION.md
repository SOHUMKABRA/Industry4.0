# API documentation

Base path `/api`. JSON in and out. Interactive OpenAPI docs are served by the
backend at `http://localhost:8000/docs` and are always current. This file
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

## WebSocket (Phase 4, design)

`GET /api/ws?ticket=<one-time ticket from POST /api/ws/ticket>`. Client → server:
`{type:"subscribe", factory_id, asset_ids?, measurements?}` and `unsubscribe`.
Server → client: `{type:"telemetry", frame:[[asset_id, measurement, value, ts, quality, source], ...]}`
coalesced per key at ≤10 Hz, plus `heartbeat` and `device_status` messages.
