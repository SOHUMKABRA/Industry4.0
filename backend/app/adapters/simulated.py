"""Simulated device adapter.

Generates time-based, repeatable signals for development, demos and tests.
Everything it produces is tagged source=simulated by ingestion. It never
touches the network, and its writes only change its own internal state.
"""

from __future__ import annotations

import math
import time
import random
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import CommandAck, DeviceAdapter, DeviceStatus, Sample
from app.schemas.devices import ConfigField, DiscoveredPoint


@dataclass(frozen=True)
class Wave:
    label: str
    unit: str
    base: float
    amp: float = 0.0
    period: float = 60.0
    noise: float = 0.05  # fraction of amp
    # Signal that only applies while the device's state point is "running"-like.
    gated: bool = False


@dataclass(frozen=True)
class Counter:
    label: str
    unit: str
    rate_per_s: float
    gated: bool = True


@dataclass(frozen=True)
class Cycle:
    """Enum signal stepping through (state, seconds) phases."""

    label: str
    states: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Const:
    label: str
    value: Any
    unit: str = ""


Signal = Wave | Counter | Cycle | Const
RUNNING = {"running", "loaded", "run"}
# Shared so a conveyor and its drive motor with the same seed change state together.
INTERMITTENT = (("running", 120.0), ("stopped", 40.0), ("running", 90.0), ("fault", 25.0))


@dataclass(frozen=True)
class Profile:
    signals: dict[str, Signal] = field(default_factory=dict)
    state_point: str | None = None  # gates Wave(gated)/Counter signals


PROFILES: dict[str, Profile] = {
    "temperature": Profile({"temp": Wave("Temperature", "°C", 55, 12, 300)}),
    # Runs hot: crosses the 70 °C warning and 80 °C alarm limits periodically.
    "temperature_hot": Profile({"temp": Wave("Temperature", "°C", 71, 11, 240)}),
    "pressure": Profile({"pressure": Wave("Pressure", "bar", 6.2, 0.6, 120)}),
    "motor": Profile(
        {
            "state": Const("State", "running"),
            "rpm": Wave("Speed", "rpm", 1450, 30, 60, gated=True),
            "current": Wave("Current", "A", 18, 2, 45, gated=True),
            "winding_temp": Wave("Winding temperature", "°C", 62, 6, 400),
            "vibration": Wave("Vibration", "mm/s", 2.1, 0.5, 30, gated=True),
        },
        state_point="state",
    ),
    "motor_intermittent": Profile(
        {
            "state": Cycle("State", INTERMITTENT),
            "rpm": Wave("Speed", "rpm", 1440, 25, 60, gated=True),
            "current": Wave("Current", "A", 14, 2, 45, gated=True),
            "winding_temp": Wave("Winding temperature", "°C", 58, 5, 400),
            "vibration": Wave("Vibration", "mm/s", 2.4, 0.6, 30, gated=True),
        },
        state_point="state",
    ),
    "energy": Profile(
        {
            "power_kw": Wave("Active power", "kW", 42, 8, 200),
            "voltage": Wave("Voltage L-L", "V", 400, 4, 90),
            "energy_kwh": Counter("Energy", "kWh", 42 / 3600, gated=False),
            "power_factor": Wave("Power factor", "", 0.94, 0.02, 300),
        }
    ),
    "flow": Profile({"flow": Wave("Flow rate", "m³/h", 24, 3, 150)}),
    "level": Profile({"level_pct": Wave("Level", "%", 62, 15, 900), "temp": Wave("Temperature", "°C", 21, 1, 600)}),
    "conveyor": Profile(
        {
            "state": Const("State", "running"),
            "speed_mps": Wave("Belt speed", "m/s", 1.2, 0.03, 40, gated=True),
            "item_count": Counter("Items conveyed", "pcs", 0.5),
        },
        state_point="state",
    ),
    "conveyor_intermittent": Profile(
        {
            "state": Cycle("State", INTERMITTENT),
            "speed_mps": Wave("Belt speed", "m/s", 0.9, 0.03, 40, gated=True),
            "item_count": Counter("Items conveyed", "pcs", 0.4),
        },
        state_point="state",
    ),
    "line": Profile(
        {"state": Const("Line state", "running"), "output_count": Counter("Output count", "pcs", 1 / 90)},
        state_point="state",
    ),
    "robot": Profile(
        {
            "state": Cycle("State", (("running", 200), ("idle", 30))),
            "program": Const("Active program", "ASSY_PUMP_01"),
            "cycle_count": Counter("Cycle count", "", 1 / 12),
            "cycle_time_s": Wave("Last cycle time", "s", 12, 0.6, 50, gated=True),
            "error_code": Const("Error code", ""),
        },
        state_point="state",
    ),
    "pump": Profile(
        {
            "state": Const("State", "running"),
            "flow": Wave("Flow", "m³/h", 23, 2, 120, gated=True),
            "discharge_pressure": Wave("Discharge pressure", "bar", 6.5, 0.4, 90, gated=True),
        },
        state_point="state",
    ),
    "panel": Profile({"estop_status": Const("E-stop circuit", "healthy"), "cabinet_temp": Wave("Cabinet temperature", "°C", 34, 3, 600)}),
    "plc": Profile({"run_mode": Const("Run mode", "run"), "scan_time_ms": Wave("Scan time", "ms", 8, 1.5, 20)}),
}


def _cycle_state(states: tuple[tuple[str, float], ...], t: float) -> str:
    total = sum(d for _, d in states)
    pos = t % total
    for s, d in states:
        if pos < d:
            return s
        pos -= d
    return states[-1][0]


class SimulatedAdapter(DeviceAdapter):
    key = "simulated"
    name = "Simulated device"
    description = "Software-generated signals for testing configurations without hardware."
    config_schema = [
        ConfigField(
            key="profile", label="Signal profile", type="enum", required=True,
            default="temperature", options=sorted(PROFILES),
        ),
        ConfigField(key="seed", label="Random seed", type="integer", default=1,
                    help="Also shifts the phase of the signals so devices differ"),
        ConfigField(
            key="fail_test", label="Simulate connection failure", type="boolean", default=False,
            help="Makes 'Test connection' fail and stops data, to exercise offline handling.",
        ),
    ]
    supports_discovery = True
    supports_write = True

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None):
        super().__init__(config, credentials)
        seed = int(config.get("seed", 1) or 1)
        self._rng = random.Random(seed)
        # Phase offset per device so identical profiles don't move in lockstep.
        self._phase = (zlib.crc32(str(seed).encode()) % 10_000) / 10.0
        self._seq = 0
        self._connected = False
        self._outputs: dict[str, Any] = {}
        # Scenario/fault injection (simulation only): point -> (value, until_epoch)
        self.overrides: dict[str, tuple[Any, float]] = {}
        self.offline_until: float = 0.0

    @property
    def profile(self) -> Profile:
        return PROFILES.get(self.config.get("profile", "temperature"), Profile())

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def test_connection(self) -> tuple[bool, str]:
        if self.config.get("fail_test"):
            return False, "Simulated failure: device did not respond (timeout)"
        return True, f"Simulator ready, profile '{self.config.get('profile')}' with {len(self.profile.signals)} points"

    async def discover_capabilities(self) -> list[DiscoveredPoint]:
        out = []
        for p, sig in self.profile.signals.items():
            dt = "string" if isinstance(sig, (Cycle, Const)) and not isinstance(getattr(sig, "value", None), (int, float)) else "number"
            out.append(DiscoveredPoint(point=p, label=sig.label, data_type=dt, unit=getattr(sig, "unit", ""), suggested_measurement=p))
        return out

    def _running(self, t: float) -> bool:
        sp = self.profile.state_point
        if not sp:
            return True
        if sp in self._outputs:
            return str(self._outputs[sp]) in RUNNING
        sig = self.profile.signals[sp]
        state = sig.value if isinstance(sig, Const) else _cycle_state(sig.states, t)  # type: ignore[union-attr]
        return state in RUNNING

    @staticmethod
    def _counter(sig: "Counter", t: float) -> Any:
        # Daily counter (resets at midnight UTC, like a shift/day production count).
        v = (t % 86_400) * sig.rate_per_s
        return int(v) if sig.unit in ("pcs", "") else round(v, 3)

    def inject(self, point: str, value: Any, duration_s: float) -> None:
        self.overrides[point] = (value, time.time() + duration_s)

    def go_offline(self, duration_s: float) -> None:
        self.offline_until = time.time() + duration_s

    def restore(self) -> None:
        self.overrides.clear()
        self.offline_until = 0.0

    def value_at(self, point: str, t: float) -> Any:
        sig = self.profile.signals[point]
        tt = t + self._phase
        ov = self.overrides.get(point)
        if ov is not None:
            if time.time() < ov[1]:
                return ov[0]
            self.overrides.pop(point, None)
        if isinstance(sig, Wave) and sig.gated and not self._running(tt):
            return 0.0
        if point in self._outputs:
            out = self._outputs[point]
            if isinstance(sig, Wave) and isinstance(out, (int, float)) and not isinstance(out, bool):
                return round(float(out) + self._rng.gauss(0, max(abs(float(out)) * 0.003, 1e-6)), 3)
            return out
        if isinstance(sig, Const):
            return sig.value
        if isinstance(sig, Cycle):
            return _cycle_state(sig.states, tt)
        if isinstance(sig, Counter):
            return self._counter(sig, t)
        if sig.gated and not self._running(tt):
            return 0.0
        wave = sig.amp * math.sin(2 * math.pi * tt / sig.period) if sig.period else 0
        noise = self._rng.gauss(0, sig.amp * sig.noise) if sig.amp else 0
        return round(sig.base + wave + noise, 3)

    async def read_telemetry(self, points: list[str]) -> list[Sample]:
        now = datetime.now(UTC)
        if self.config.get("fail_test") or time.time() < self.offline_until:
            return []
        out = []
        for p in points:
            if p not in self.profile.signals:
                out.append(Sample(point=p, value=None, ts=now, quality="bad"))
                continue
            self._seq += 1
            out.append(Sample(point=p, value=self.value_at(p, now.timestamp()), ts=now, seq=self._seq))
        return out

    async def write_command(self, point: str, value: Any) -> CommandAck:
        self._outputs[point] = value
        return CommandAck(accepted=True, message=f"simulated write {point}={value!r}")

    async def get_device_status(self) -> DeviceStatus:
        return DeviceStatus(
            connected=self._connected,
            detail="simulated",
            diagnostics={"samples_generated": self._seq, "outputs": dict(self._outputs)},
        )
