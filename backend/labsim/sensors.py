"""MQTT field transmitters for the lab simulator.

Publishes JSON once per second like real IIoT transmitters:
  riverside/hall-a/tt-101   {"temp", "ts", "seq"}
  riverside/hall-a/tt-201   {"temp", "ts", "seq"}
  riverside/utilities/em-001 {"power_kw", "voltage", "energy_kwh", "power_factor", "ts", "seq"}
  riverside/hall-a/em-002   {"power_kw", "voltage", "ts", "seq"}
Power draw follows the virtual PLC (line and pump running).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field

import aiomqtt

from labsim.plc import Line3Plc

log = logging.getLogger("labsim.mqtt")


@dataclass
class SensorFaults:
    overheat_until: float = 0.0
    disconnected: set[str] = field(default_factory=set)


class Transmitters:
    def __init__(self, plc: Line3Plc, host: str = "127.0.0.1", port: int = 1883):
        self.plc = plc
        self.host, self.port = host, port
        self.faults = SensorFaults()
        self.seq = 0
        self.energy = (time.time() % 86400) * 42 / 3600
        self.rng = random.Random(7)
        self.connected = False
        self.last: dict[str, dict] = {}

    def overheat(self, seconds: int = 90) -> None:
        self.faults.overheat_until = time.time() + seconds
        self.plc.log(f"TT-101 coolant overheating for {seconds}s (chiller failure)")

    def toggle_disconnect(self, tag: str) -> bool:
        if tag in self.faults.disconnected:
            self.faults.disconnected.discard(tag)
            self.plc.log(f"{tag.upper()} transmitter reconnected")
            return False
        self.faults.disconnected.add(tag)
        self.plc.log(f"{tag.upper()} transmitter disconnected (cable pulled)")
        return True

    def readings(self) -> dict[str, tuple[str, dict]]:
        t = time.time()
        g = self.rng.gauss
        st = self.plc.status()
        line_kw = 7.5 * (st["speed_mps"] / 1.2) if st["speed_mps"] else 0.0
        pump_kw = 5.5 * (st["pump_flow"] / 23)
        base_kw = 31 + 6 * math.sin(t / 200)
        hot = max(0.0, self.faults.overheat_until - t)
        overheat = 38 * min(1.0, (90 - hot) / 25) if hot > 0 else 0.0
        self.energy += (base_kw + line_kw + pump_kw) / 3600
        return {
            "tt-101": ("riverside/hall-a/tt-101", {"temp": round(52 + 6 * math.sin(t / 300) + overheat + g(0, 0.3), 2)}),
            "tt-201": ("riverside/hall-a/tt-201", {"temp": round(24 + 1.5 * math.sin(t / 900) + g(0, 0.15), 2)}),
            "em-001": ("riverside/utilities/em-001", {
                "power_kw": round(base_kw + line_kw + pump_kw + g(0, 0.4), 2), "voltage": round(400 + 3 * math.sin(t / 90) + g(0, 0.5), 1),
                "energy_kwh": round(self.energy, 3), "power_factor": round(0.93 + 0.02 * math.sin(t / 400), 3)}),
            "em-002": ("riverside/hall-a/em-002", {"power_kw": round(12 + 3 * math.sin(t / 150) + g(0, 0.3), 2),
                                                   "voltage": round(399 + 2 * math.sin(t / 70) + g(0, 0.4), 1)}),
        }

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(self.host, self.port, identifier="labsim-transmitters") as client:
                    self.connected = True
                    backoff = 1.0
                    while True:
                        self.seq += 1
                        ts = int(time.time() * 1000)
                        for tag, (topic, body) in self.readings().items():
                            if tag in self.faults.disconnected:
                                continue
                            payload = {**body, "ts": ts, "seq": self.seq}
                            self.last[tag] = payload
                            await client.publish(topic, json.dumps(payload), qos=0)
                        await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.connected = False
                log.warning("MQTT publisher: %s; retry in %.0fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)
