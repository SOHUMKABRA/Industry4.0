"""Modbus TCP adapter (pymodbus).

Point address syntax:  <table>:<address>[:<type>][:map=<raw>=<text>;...]
  table   hr (holding register), ir (input register), co (coil), di (discrete input)
  address 0-based protocol address (register 40001 → hr:0)
  type    uint16 (default) | int16 | uint32 | int32 | float32   (registers only)
  map     integer → text, e.g. hr:1:uint16:map=0=stopped;1=running;2=fault

Examples:  hr:2  ir:10:float32  co:0  hr:1:uint16:map=0=stopped;1=running
"""

from __future__ import annotations

import asyncio
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from app.adapters.base import AdapterError, CommandAck, DeviceAdapter, DeviceStatus, Sample
from app.schemas.devices import ConfigField, DiscoveredPoint

TABLES = {"hr", "ir", "co", "di"}
WIDTH = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}
MAX_REG_BLOCK = 100


@dataclass(frozen=True)
class Point:
    raw: str
    table: str
    address: int
    dtype: str
    mapping: dict[int, str]

    @property
    def width(self) -> int:
        return 1 if self.table in ("co", "di") else WIDTH[self.dtype]


def parse_point(raw: str) -> Point:
    parts = raw.strip().split(":")
    if len(parts) < 2 or parts[0] not in TABLES:
        raise AdapterError(f"Invalid Modbus point '{raw}': expected e.g. hr:0, ir:10:float32, co:3")
    try:
        address = int(parts[1])
    except ValueError:
        raise AdapterError(f"Invalid Modbus address in '{raw}'") from None
    if not 0 <= address <= 65535:
        raise AdapterError(f"Modbus address out of range in '{raw}'")
    dtype, mapping = "uint16", {}
    for extra in parts[2:]:
        if extra.startswith("map="):
            for pair in extra[4:].split(";"):
                if pair:
                    k, _, v = pair.partition("=")
                    mapping[int(k)] = v
        elif extra in WIDTH:
            dtype = extra
        else:
            raise AdapterError(f"Unknown Modbus data type '{extra}' in '{raw}'")
    return Point(raw, parts[0], address, dtype, mapping)


class ModbusTcpAdapter(DeviceAdapter):
    key = "modbus_tcp"
    name = "Modbus TCP"
    description = "Poll holding/input registers, coils and discrete inputs; write coils and holding registers."
    config_schema = [
        ConfigField(key="host", label="Host / IP address", type="string", required=True, help="PLC, gateway or meter address"),
        ConfigField(key="port", label="Port", type="integer", default=502),
        ConfigField(key="unit_id", label="Unit / slave ID", type="integer", default=1),
        ConfigField(key="timeout_s", label="Timeout (s)", type="number", default=2.0),
        ConfigField(key="byte_order", label="Byte order (32-bit)", type="enum", default="big", options=["big", "little"]),
        ConfigField(key="word_order", label="Word order (32-bit)", type="enum", default="big", options=["big", "little"],
                    help="'little' = low word first (common on some PLCs)"),
        ConfigField(key="discover_table", label="Discovery: table", type="enum", default="hr", options=["hr", "ir", "co", "di"]),
        ConfigField(key="discover_start", label="Discovery: start address", type="integer", default=0),
        ConfigField(key="discover_count", label="Discovery: count", type="integer", default=20),
    ]
    supports_discovery = True
    supports_write = True

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None):
        super().__init__(config, credentials)
        self.client: AsyncModbusTcpClient | None = None
        self._lock = asyncio.Lock()
        self._reads = 0
        self._errors = 0
        self._last_latency_ms: float | None = None
        self._last_error = ""

    @property
    def unit(self) -> int:
        return int(self.config.get("unit_id", 1))

    async def connect(self) -> None:
        if self.client and self.client.connected:
            return
        self.client = AsyncModbusTcpClient(
            self.config["host"], port=int(self.config.get("port", 502)),
            timeout=float(self.config.get("timeout_s", 2.0)), retries=1, reconnect_delay=0,
        )
        ok = await self.client.connect()
        if not ok:
            raise AdapterError(f"Connection refused or unreachable: {self.config['host']}:{self.config.get('port', 502)}")

    async def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self.connect()
            t0 = time.perf_counter()
            rr = await self.client.read_holding_registers(0, count=1, device_id=self.unit)
            ms = (time.perf_counter() - t0) * 1000
            if rr.isError():
                return True, f"Connected; device answered with Modbus exception for hr:0 ({rr}). Check your register map. {ms:.0f} ms"
            return True, f"Connected to {self.config['host']}:{self.config.get('port', 502)} unit {self.unit}; read hr:0 = {rr.registers[0]} in {ms:.0f} ms"
        except Exception as e:  # noqa: BLE001 - report every failure to the operator
            return False, f"{type(e).__name__}: {e}"
        finally:
            await self.disconnect()

    # ---- decoding ----
    def _decode(self, p: Point, regs: list[int]) -> Any:
        if p.dtype in ("uint16", "int16"):
            v = regs[0]
            if p.dtype == "int16" and v >= 0x8000:
                v -= 0x10000
        else:
            words = regs[:2] if self.config.get("word_order", "big") == "big" else regs[1::-1]
            raw = b"".join(w.to_bytes(2, "big") for w in words)
            if self.config.get("byte_order", "big") == "little":
                raw = raw[::-1]
            fmt = {"uint32": ">I", "int32": ">i", "float32": ">f"}[p.dtype]
            v = struct.unpack(fmt, raw)[0]
            if p.dtype == "float32":
                v = round(v, 6)
        return p.mapping.get(int(v), v) if p.mapping else v

    def _encode(self, p: Point, value: Any) -> list[int]:
        if p.mapping and isinstance(value, str):
            rev = {v: k for k, v in p.mapping.items()}
            if value not in rev:
                raise AdapterError(f"Value '{value}' not in point map {p.mapping}")
            value = rev[value]
        if p.dtype in ("uint16", "int16"):
            v = int(round(float(value)))
            if not (-32768 if p.dtype == "int16" else 0) <= v <= (32767 if p.dtype == "int16" else 65535):
                raise AdapterError(f"Value {value} out of range for {p.dtype}")
            return [v & 0xFFFF]
        fmt = {"uint32": ">I", "int32": ">i", "float32": ">f"}[p.dtype]
        raw = struct.pack(fmt, float(value) if p.dtype == "float32" else int(round(float(value))))
        if self.config.get("byte_order", "big") == "little":
            raw = raw[::-1]
        words = [int.from_bytes(raw[0:2], "big"), int.from_bytes(raw[2:4], "big")]
        return words if self.config.get("word_order", "big") == "big" else words[::-1]

    async def _read_block(self, table: str, start: int, count: int) -> list:
        c = self.client
        fn = {"hr": c.read_holding_registers, "ir": c.read_input_registers, "co": c.read_coils, "di": c.read_discrete_inputs}[table]
        rr = await fn(start, count=count, device_id=self.unit)
        if rr.isError():
            raise AdapterError(f"Modbus exception reading {table}:{start}+{count}: {rr}")
        return list(rr.bits[:count]) if table in ("co", "di") else list(rr.registers)

    async def read_telemetry(self, points: list[str]) -> list[Sample]:
        parsed: list[Point] = []
        bad: list[Sample] = []
        now = datetime.now(UTC)
        for raw in points:
            try:
                parsed.append(parse_point(raw))
            except AdapterError:
                bad.append(Sample(raw, None, now, "bad"))
        async with self._lock:
            t0 = time.perf_counter()
            try:
                await self.connect()
                out: list[Sample] = []
                # Group by table and read contiguous blocks to minimise requests.
                for table in TABLES:
                    pts = sorted((p for p in parsed if p.table == table), key=lambda p: p.address)
                    i = 0
                    while i < len(pts):
                        start = pts[i].address
                        j = i
                        while j + 1 < len(pts) and pts[j + 1].address + pts[j + 1].width - start <= MAX_REG_BLOCK:
                            j += 1
                        end = max(p.address + p.width for p in pts[i:j + 1])
                        data = await self._read_block(table, start, end - start)
                        ts = datetime.now(UTC)
                        for p in pts[i:j + 1]:
                            off = p.address - start
                            if table in ("co", "di"):
                                val: Any = bool(data[off])
                                val = p.mapping.get(int(val), val) if p.mapping else val
                            else:
                                val = self._decode(p, data[off:off + p.width])
                            out.append(Sample(p.raw, val, ts))
                        i = j + 1
                self._reads += 1
                self._last_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                self._last_error = ""
                return out + bad
            except Exception as e:
                self._errors += 1
                self._last_error = f"{type(e).__name__}: {e}"
                await self.disconnect()  # force a clean reconnect next poll
                raise

    async def write_command(self, point: str, value: Any) -> CommandAck:
        p = parse_point(point)
        if p.table in ("ir", "di"):
            raise AdapterError(f"{point} is read-only (input table)")
        async with self._lock:
            await self.connect()
            if p.table == "co":
                if isinstance(value, str):
                    value = value.lower() in ("1", "true", "on", "start", "run")
                rr = await self.client.write_coil(p.address, bool(value), device_id=self.unit)
            else:
                words = self._encode(p, value)
                if len(words) == 1:
                    rr = await self.client.write_register(p.address, words[0], device_id=self.unit)
                else:
                    rr = await self.client.write_registers(p.address, words, device_id=self.unit)
        if rr.isError():
            return CommandAck(False, f"Device rejected write to {point}: {rr}")
        return CommandAck(True, f"Device acknowledged write {point} = {value!r}")

    async def discover_capabilities(self) -> list[DiscoveredPoint]:
        table = self.config.get("discover_table", "hr")
        start = int(self.config.get("discover_start", 0))
        count = max(1, min(int(self.config.get("discover_count", 20)), 125))
        try:
            await self.connect()
            data = await self._read_block(table, start, count)
        finally:
            await self.disconnect()
        return [
            DiscoveredPoint(point=f"{table}:{start + i}", label=f"{table.upper()} {start + i} = {int(v) if isinstance(v, bool) else v}",
                            data_type="boolean" if table in ("co", "di") else "number")
            for i, v in enumerate(data)
        ]

    async def get_device_status(self) -> DeviceStatus:
        return DeviceStatus(
            connected=bool(self.client and self.client.connected),
            detail=self._last_error,
            diagnostics={"reads": self._reads, "errors": self._errors, "last_latency_ms": self._last_latency_ms},
        )
