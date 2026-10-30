"""Simulated device adapter.

Generates deterministic-but-varying values for development, demos and tests.
Samples it produces must always be tagged source=simulated by ingestion. It
never touches the network.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import CommandAck, DeviceAdapter, DeviceStatus, Sample
from app.schemas.devices import ConfigField, DiscoveredPoint

# Built-in signal profiles: point -> (label, unit, base, amplitude, period_s)
PROFILES: dict[str, dict[str, tuple[str, str, float, float, float]]] = {
    "temperature": {"temp": ("Temperature", "°C", 55, 12, 300)},
    "pressure": {"pressure": ("Pressure", "bar", 6.2, 0.6, 120)},
    "motor": {
        "rpm": ("Speed", "rpm", 1450, 30, 60),
        "current": ("Current", "A", 18, 2, 45),
        "winding_temp": ("Winding temperature", "°C", 62, 6, 400),
        "vibration": ("Vibration", "mm/s", 2.1, 0.5, 30),
    },
    "energy": {
        "power_kw": ("Active power", "kW", 42, 8, 200),
        "voltage": ("Voltage L-L", "V", 400, 4, 90),
        "energy_kwh": ("Energy", "kWh", 0, 0, 0),
    },
    "flow": {"flow": ("Flow rate", "m³/h", 24, 3, 150)},
    "level": {"level_pct": ("Level", "%", 62, 15, 900)},
}


class SimulatedAdapter(DeviceAdapter):
    key = "simulated"
    name = "Simulated device"
    description = "Software-generated signals for testing configurations without hardware."
    config_schema = [
        ConfigField(
            key="profile",
            label="Signal profile",
            type="enum",
            required=True,
            default="temperature",
            options=sorted(PROFILES),
        ),
        ConfigField(key="seed", label="Random seed", type="integer", default=1),
        ConfigField(
            key="fail_test",
            label="Simulate connection failure",
            type="boolean",
            default=False,
            help="Makes 'Test connection' fail, to exercise error handling.",
        ),
    ]
    supports_discovery = True
    supports_write = True

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None):
        super().__init__(config, credentials)
        self._rng = random.Random(config.get("seed", 1))
        self._seq = 0
        self._connected = False
        self._outputs: dict[str, Any] = {}

    @property
    def _profile(self) -> dict[str, tuple[str, str, float, float, float]]:
        return PROFILES.get(self.config.get("profile", "temperature"), {})

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def test_connection(self) -> tuple[bool, str]:
        if self.config.get("fail_test"):
            return False, "Simulated failure: device did not respond (timeout)"
        return True, f"Simulator ready, profile '{self.config.get('profile')}' with {len(self._profile)} points"

    async def discover_capabilities(self) -> list[DiscoveredPoint]:
        return [
            DiscoveredPoint(point=p, label=lbl, data_type="number", unit=unit, suggested_measurement=p)
            for p, (lbl, unit, *_rest) in self._profile.items()
        ]

    async def read_telemetry(self, points: list[str]) -> list[Sample]:
        now = datetime.now(UTC)
        t = now.timestamp()
        out = []
        for p in points:
            if p not in self._profile:
                out.append(Sample(point=p, value=None, ts=now, quality="bad"))
                continue
            _, _, base, amp, period = self._profile[p]
            wave = amp * math.sin(2 * math.pi * t / period) if period else 0
            noise = self._rng.gauss(0, amp * 0.05) if amp else 0
            self._seq += 1
            out.append(Sample(point=p, value=round(base + wave + noise, 3), ts=now, seq=self._seq))
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
