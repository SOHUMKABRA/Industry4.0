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

## Point mappings

A device's `point_mappings` connect protocol addresses to the bound asset's
measurements: `{point, measurement, scale, offset}` with `value = raw × scale + offset`.
Point syntax is protocol-specific:

| Protocol | Point examples |
|---|---|
| simulated | `temp`, `rpm` (profile-defined) |
| mqtt (P3) | `plant/line1/tt101` + optional JSON path: `plant/line1/motor#$.rpm` |
| modbus_tcp (P3) | `hr:40001:float32:be`, `ir:30010:int16`, `coil:5` |
| opcua (planned) | `ns=2;s=Line1.Motor.Speed` |

## Adapters

| Protocol | Status | Notes |
|---|---|---|
| Simulated | ✅ available | Profiles: temperature, pressure, motor, energy, flow, level. Can simulate a failed connection test. Never touches the network. |
| MQTT | Phase 3 | `aiomqtt`; TLS, username/password, client certs; topic discovery by sampling |
| Modbus TCP | Phase 3 | `pymodbus`; register map defined per device or per device template; byte/word order options |
| OPC UA | planned | `asyncua`; browse for discovery; subscriptions |
| HTTP poll / Webhook | planned | |
| Modbus RTU / RS485, S7, EtherNet/IP, BACnet, CAN | planned | Need serial/fieldbus hardware or vendor libraries. Edge gateway only. |
