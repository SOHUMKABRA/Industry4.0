# Device integration

## Principles

* The browser **never** talks to devices. Adapters run in the platform API process
  today and in an edge gateway later (Phase 7), on the plant network.
* Protocols are **not** interchangeable. Each adapter declares its own connection
  settings, point-addressing scheme and capabilities. The core only depends on
  the narrow interface below.
* An adapter that isn't implemented isn't offered. The protocol catalogue
  (`GET /api/protocols`) lists planned protocols as `status: "planned"`, and the
  API rejects them for new devices.
* A command **acknowledgement** from an adapter means the device accepted the
  request. It does not prove the physical action happened. The Phase 5 command
  engine verifies outcomes through telemetry.

## Adapter interface

`backend/app/adapters/base.py`

```python
class DeviceAdapter(abc.ABC):
    key: ClassVar[str]                     # protocol id, e.g. "modbus_tcp"
    name: ClassVar[str]
    description: ClassVar[str]
    config_schema: ClassVar[list[ConfigField]]   # rendered as a form in the UI
    supports_discovery: ClassVar[bool]
    supports_write: ClassVar[bool]

    def __init__(self, config: dict, credentials: dict | None): ...
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def test_connection(self) -> tuple[bool, str]      # must not change device state
    async def discover_capabilities(self) -> list[DiscoveredPoint]
    async def read_telemetry(self, points: list[str]) -> list[Sample]
    async def write_command(self, point: str, value) -> CommandAck
    async def get_device_status(self) -> DeviceStatus
    async def get_diagnostics(self) -> dict
```

`ConfigField(key, label, type: string|integer|number|boolean|enum, required, default, options, secret, help)`.
Fields with `secret=True` (passwords, API keys, client certificates) are collected
separately, encrypted with Fernet (`CREDENTIAL_KEY`), passed to the adapter
constructor as `credentials`, and never returned by the API or written to the
audit log. `validate_config()` rejects unknown keys and coerces types.

`Sample(point, value, ts, quality: good|uncertain|bad, seq)`. Adapters stamp the
time of acquisition and use `seq` (monotonic per device) when the source provides
one. Ingestion uses `(device, seq)` to drop duplicates.

## Writing an adapter

1. Create `backend/app/adapters/<protocol>.py` implementing `DeviceAdapter`.
2. Register it: `registry.register(MyAdapter)` (built-ins), or for third-party
   packages expose a `twin.adapters` entry point (loader lands in Phase 3).
3. Remove its key from `PLANNED` in `registry.py`, if present.
4. Add tests against a simulator or test server, never live equipment. See
   `tests/test_devices.py` for the expected behaviour (validation, test, discovery).

Rules:
* Every network call needs a timeout. The API also wraps adapter calls in a 10 s
  `asyncio.wait_for`.
* `test_connection` must be read-only.
* Raise `AdapterError` with a message an operator can act on ("Connection refused
  at 10.0.0.5:502", not a stack trace).
* Blocking vendor libraries must run in a thread (`asyncio.to_thread`) so the event
  loop is never blocked.

## Telemetry runtime

`app/telemetry/runtime.py` polls every enabled, asset-bound device once per
`TELEMETRY_POLL_S`, each read bounded by a 5 s timeout. Samples are mapped through
`point_mappings`. Samples with bad quality, duplicate `(device, point, seq)` or older
timestamps are filtered: older samples still go to history but never overwrite the
latest value. Accepted values update the latest-value cache, stream to WebSocket
subscribers, and are written to history in batches. Disabling or unbinding a device
removes its cached values immediately, so they can't linger as if live. Push-style
protocols (MQTT, webhooks) will feed the same `ingest()` entry point.

## Point mappings

A device's `point_mappings` connect protocol addresses to the bound asset's
measurements: `{point, measurement, scale, offset}` with `value = raw × scale + offset`.
Point syntax is protocol-specific:

| Protocol | Point examples |
|---|---|
| simulated | `temp`, `rpm` (profile-defined) |
| mqtt | `plant/line1/tt101` (raw) or `plant/line1/motor#rpm` / `#data.motor.rpm` (JSON) |
| modbus_tcp | `hr:0` (uint16) · `ir:10:float32` · `hr:3:uint32` · `co:0` · `di:4` · `hr:1:uint16:map=0=stopped;1=running;2=fault` |
| opcua (planned) | `ns=2;s=Line1.Motor.Speed` |

## Adapters

| Protocol | Status | Notes |
|---|---|---|
| Simulated | ✅ available | 15 profiles: temperature, temperature_hot (crosses limits), pressure, motor, motor_intermittent, energy, flow, level, conveyor, conveyor_intermittent (running/stopped/fault cycle), line, robot, pump, panel, plc. Speed/current signals read 0 whenever the profile's state isn't running. Counters reset daily. `fail_test` makes it fail tests and stop sending data (offline handling). Never touches the network. |
| Modbus TCP | ✅ available | `pymodbus`. Point syntax `table:address[:type][:map=…]` (see below). Block reads, persistent connection, register-scan discovery, writes to coils / holding registers |
| MQTT | ✅ available | `aiomqtt`, push-based. Point syntax `topic#json.path` or `topic` (raw). TLS, username/password (encrypted). Topic-sniffing discovery. Commands publish `{"value", "command_id", "ts"}` |
| OPC UA | planned | `asyncua`; browse for discovery; subscriptions |
| HTTP poll / Webhook | planned | |
| Modbus RTU / RS485, S7, EtherNet/IP, BACnet, CAN | planned | Need serial/fieldbus hardware or vendor libraries. Edge gateway only. |

### Modbus TCP details

* Addresses are **0-based protocol addresses** (holding register 40001 → `hr:0`).
* 32-bit types use two registers; set *Byte order* / *Word order* per device to match the PLC (many PLCs need word order `little`).
* `map=` turns integer state codes into the text states your asset type expects (`running`, `fault`, …), in both directions for commands.
* *Scale*/*Offset* in the point mapping convert raw counts to engineering units (e.g. `hr:2` cm/s × 0.01 → m/s).

## Command (control) mappings

Each device can map asset-type controls to protocol points:

| Field | Meaning |
|---|---|
| `control` | Control key on the asset type (`start`, `stop`, `speed_setpoint`, …) |
| `point` | Where to write: `co:0`, `hr:12`, an MQTT topic, or a simulator point |
| `value` | Value written for commands without parameters (`true`, `1`, `"running"`) |
| `param` + `scale` | Setpoints: the parameter's value × scale is written (e.g. m/s × 100 → cm/s register) |

Only `co:` and `hr:` points can be written; input tables are rejected when you save.
A device acknowledgement is **not** treated as success: the control engine waits for
the control's `feedback_measurement` to reach the expected value (`feedback_value`, or
the setpoint ± `feedback_tolerance`) within `timeout_s`.

## Device templates

`GET/POST /api/device-templates` store reusable protocol settings, point maps and command
maps. Built-in templates: line-PLC conveyor and pump (Modbus TCP), float32 energy meter
(Modbus TCP), MQTT JSON temperature transmitter and energy meter, simulated conveyor.
Choose one in step 1 of the onboarding wizard and adjust addresses/topics for the real device.

## Connecting the customer's machinery (checklist)

1. Get the register map (Modbus) or topic/payload description (MQTT) for each machine.
2. Create or reuse an **asset type** with the measurements and controls you need (Asset types page).
3. **Connect device**: pick the asset, start from a template, enter the IP/port/unit or broker, **Test**, **Discover**, map points and (optionally) commands, then activate.
4. Add **interlocks** on the asset's Control tab for anything that must be true before starting (E-stop healthy, guards closed, downstream running, levels OK).
5. Test every command on site with the machine in a safe state, with local supervision.
