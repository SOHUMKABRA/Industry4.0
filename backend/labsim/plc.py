"""Virtual Line-3 PLC (Modbus TCP) for demos and integration tests.

It runs its own control logic like a real PLC: the platform can only request
things by writing coils/registers; the PLC decides. An E-stop or a fault drops
the run outputs inside the PLC regardless of what the platform asks.

Register map (unit 1, 0-based addresses)
  coils     0  line-3 conveyor run request (drives CV-301 + MTR-301)
            1  coolant pump PMP-401 run request
  holding   0  conveyor speed setpoint, cm/s (0–200, default 90)
            1  CV-301 state    (0 stopped, 1 running, 2 fault, 3 maintenance, 4 emergency_stop)
            2  CV-301 speed, cm/s
            3–4 CV-301 item count (uint32, big-endian words)
           10  MTR-301 state   11 rpm   12 current ×10 A   13 winding temp ×10 °C   14 vibration ×100 mm/s
           20  PMP-401 state   21 flow ×10 m³/h   22 discharge pressure ×100 bar
           30  E-stop circuit  (0 healthy, 1 tripped)   31 cabinet temp ×10 °C
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field

from labsim.modbus_server import DataStore, ModbusTcpSlave

STOPPED, RUNNING, FAULT, MAINT, ESTOP = 0, 1, 2, 3, 4
NOMINAL_CMS = 120.0  # conveyor speed at rated motor speed
RATED_RPM = 1450.0


@dataclass
class PlcState:
    estop: bool = False
    jam: bool = False
    pump_fault: bool = False
    speed_cms: float = 0.0
    items: float = 0.0
    pump_flow: float = 0.0
    pump_starting_since: float | None = None
    winding_c: float = 32.0
    events: list[str] = field(default_factory=list)


class Line3Plc:
    SCAN_S = 0.1

    def __init__(self) -> None:
        self.store = DataStore()
        self.slave = ModbusTcpSlave(self.store)
        self.s = PlcState()
        self._set_hr(0, 90)
        self._rng = random.Random(3)
        self._last = time.monotonic()

    # --- raw access (wire addresses) ---
    def _get_hr(self, a: int) -> int:
        return self.store.hr[a]

    def _set_hr(self, a: int, v: float) -> None:
        self.store.hr[a] = max(0, min(65535, int(round(v))))

    def _get_co(self, a: int) -> bool:
        return self.store.co[a]

    def _set_co(self, a: int, v: bool) -> None:
        self.store.co[a] = bool(v)

    def log(self, msg: str) -> None:
        self.s.events = [f"{time.strftime('%H:%M:%S')}  {msg}", *self.s.events][:30]

    # --- presenter actions (physical-world events) ---
    def press_estop(self) -> None:
        self.s.estop = True
        self.log("E-STOP pressed (physical button)")

    def reset_estop(self) -> None:
        self.s.estop = False
        self.log("E-stop reset by operator at the panel")

    def jam_conveyor(self) -> None:
        self.s.jam = True
        self.log("Conveyor CV-301 jammed: drive overload trip")

    def clear_faults(self) -> None:
        self.s.jam = False
        self.s.pump_fault = False
        self.log("Faults cleared by maintenance (local reset)")

    def pump_trip(self) -> None:
        self.s.pump_fault = True
        self.log("Pump PMP-401 motor protection tripped")

    # --- scan cycle ---
    def scan(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last, 0.5)
        self._last = now
        s, rnd = self.s, self._rng

        # Safety logic first: E-stop and faults drop the run requests (PLC-side, independent of SCADA).
        if s.estop and (self._get_co(0) or self._get_co(1)):
            self._set_co(0, False)
            self._set_co(1, False)
            self.log("PLC dropped all run outputs (E-stop)")
        if s.jam and self._get_co(0):
            self._set_co(0, False)
            self.log("PLC dropped conveyor run (fault latched)")
        if s.pump_fault and self._get_co(1):
            self._set_co(1, False)

        run_line = self._get_co(0)
        sp = max(0, min(200, self._get_hr(0)))
        target = sp if run_line else 0.0
        accel = 40.0 * dt
        s.speed_cms += max(-accel * 1.5, min(accel, target - s.speed_cms))
        if abs(s.speed_cms - target) < 0.5:
            s.speed_cms = float(target)
        if s.jam:
            s.speed_cms = 0.0
        s.items += s.speed_cms / 100.0 * 0.5 * dt

        if s.estop:
            line_state = ESTOP
        elif s.jam:
            line_state = FAULT
        else:
            # Still "running" while decelerating; "stopped" once the belt is at rest.
            line_state = RUNNING if (run_line or s.speed_cms > 0.5) else STOPPED

        frac = s.speed_cms / NOMINAL_CMS
        rpm = frac * RATED_RPM
        current = (3.2 + 11.5 * frac + (14 if s.jam else 0)) if (frac > 0.01 or s.jam) else 0.0
        s.winding_c += ((34 + 30 * frac + (25 if s.jam else 0)) - s.winding_c) * dt / 60
        vib = (1.6 + 0.9 * frac) if frac > 0.01 else 0.2

        self._set_hr(1, line_state)
        self._set_hr(2, s.speed_cms)
        items = int(s.items)
        self._set_hr(3, items >> 16)
        self._set_hr(4, items & 0xFFFF)
        self._set_hr(10, line_state)
        self._set_hr(11, rpm + (rnd.gauss(0, 4) if rpm > 1 else 0))
        self._set_hr(12, current * 10 + (rnd.gauss(0, 2) if current else 0))
        self._set_hr(13, s.winding_c * 10)
        self._set_hr(14, vib * 100 + rnd.gauss(0, 4))

        # Pump: 1.5 s start delay, then flow ramps up.
        run_pump = self._get_co(1)
        if run_pump and s.pump_starting_since is None:
            s.pump_starting_since = now
        if not run_pump:
            s.pump_starting_since = None
        pumping = run_pump and s.pump_starting_since is not None and now - s.pump_starting_since > 1.5
        target_flow = 23.0 if pumping else 0.0
        s.pump_flow += (target_flow - s.pump_flow) * min(1.0, dt * 1.2)
        if s.estop:
            pump_state = ESTOP
        elif s.pump_fault:
            pump_state = FAULT
        else:
            pump_state = RUNNING if pumping else STOPPED
        self._set_hr(20, pump_state)
        self._set_hr(21, max(0.0, s.pump_flow * 10 + (rnd.gauss(0, 2) if pumping else 0)))
        self._set_hr(22, (6.4 * s.pump_flow / 23 + 0.2) * 100 + (rnd.gauss(0, 3) if pumping else 0))

        self._set_hr(30, 1 if s.estop else 0)
        self._set_hr(31, (33.5 + 2 * math.sin(time.time() / 300)) * 10)

    def status(self) -> dict:
        names = {0: "stopped", 1: "running", 2: "fault", 3: "maintenance", 4: "emergency_stop"}
        return {
            "estop": self.s.estop, "jam": self.s.jam, "pump_fault": self.s.pump_fault,
            "line_run_request": self._get_co(0), "pump_run_request": self._get_co(1),
            "conveyor_state": names[self._get_hr(1)], "speed_mps": round(self._get_hr(2) / 100, 2),
            "speed_setpoint_mps": round(self._get_hr(0) / 100, 2), "motor_rpm": self._get_hr(11),
            "pump_state": names[self._get_hr(20)], "pump_flow": round(self._get_hr(21) / 10, 1),
            "items": int(self.s.items), "events": self.s.events,
        }

    async def run(self, host: str = "127.0.0.1", port: int = 5020) -> None:
        scan = asyncio.create_task(self._scan_loop())
        try:
            await self.slave.serve(host, port)
        finally:
            scan.cancel()

    async def _scan_loop(self) -> None:
        while True:
            self.scan()
            await asyncio.sleep(self.SCAN_S)

    async def stop(self) -> None:
        await self.slave.stop()
