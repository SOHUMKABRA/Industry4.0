"""Simulation scenarios: scripted fault injection on *simulated* devices.

Used to rehearse alarms, interlocks and automations without hardware. The runner
refuses any device that isn't a simulated device in the telemetry runtime, so a
scenario can never act on field equipment.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.adapters.simulated import SimulatedAdapter
from app.telemetry.runtime import TelemetryRuntime

log = logging.getLogger("twin.simulation")


class SimulationError(Exception):
    pass


@dataclass
class Run:
    scenario_id: str
    name: str
    factory_id: str
    org_id: str
    started_by: str
    started_at: float
    duration_s: float
    log: list[str] = field(default_factory=list)
    done: bool = False
    task: asyncio.Task | None = None
    touched: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "name": self.name, "started_by": self.started_by,
                "started_at": int(self.started_at * 1000), "duration_s": self.duration_s,
                "elapsed_s": round(time.time() - self.started_at, 1), "done": self.done, "log": self.log[-50:]}


def sim_adapter(runtime: TelemetryRuntime | None, device_id: str, org_id: str) -> SimulatedAdapter:
    ctx = runtime.devices.get(device_id) if runtime else None
    if ctx is None or ctx.org_id != org_id:
        raise SimulationError("Device is not active (enable it first)")
    if ctx.protocol != "simulated" or not isinstance(ctx.adapter, SimulatedAdapter):
        raise SimulationError(f"{ctx.name} is a field device ({ctx.protocol}); simulation only acts on simulated devices")
    return ctx.adapter


def apply_step(runtime: TelemetryRuntime, org_id: str, step: dict[str, Any]) -> str:
    ad = sim_adapter(runtime, step["device_id"], org_id)
    name = runtime.devices[step["device_id"]].name
    action = step["action"]
    dur = float(step.get("duration_s") or 60)
    if action == "set":
        if step["point"] not in ad.profile.signals:
            raise SimulationError(f"{name} has no point '{step['point']}'")
        ad.inject(step["point"], step["value"], dur)
        return f"{name}: {step['point']} = {step['value']} for {dur:g}s"
    if action == "offline":
        ad.go_offline(dur)
        return f"{name}: offline for {dur:g}s"
    if action == "restore":
        ad.restore()
        return f"{name}: restored"
    raise SimulationError(f"Unknown action '{action}'")


class ScenarioRunner:
    def __init__(self, runtime: TelemetryRuntime | None):
        self.runtime = runtime
        self.runs: dict[str, Run] = {}  # factory_id -> current/last run

    def validate(self, org_id: str, steps: list[dict[str, Any]]) -> None:
        for s in steps:
            sim_adapter(self.runtime, s["device_id"], org_id)

    def start(self, scenario: dict[str, Any], user_email: str) -> Run:
        cur = self.runs.get(scenario["factory_id"])
        if cur and not cur.done:
            raise SimulationError(f"Scenario '{cur.name}' is already running")
        steps = sorted(scenario["steps"], key=lambda s: float(s.get("at_s", 0)))
        self.validate(scenario["org_id"], steps)
        dur = max((float(s.get("at_s", 0)) + float(s.get("duration_s") or 0) for s in steps), default=0)
        run = Run(scenario["id"], scenario["name"], scenario["factory_id"], scenario["org_id"], user_email, time.time(), dur)
        self.runs[scenario["factory_id"]] = run
        run.task = asyncio.get_running_loop().create_task(self._play(run, steps))
        return run

    async def _play(self, run: Run, steps: list[dict[str, Any]]) -> None:
        try:
            run.log.append(f"t+0s  started by {run.started_by}")
            for s in steps:
                wait = run.started_at + float(s.get("at_s", 0)) - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    msg = apply_step(self.runtime, run.org_id, s)
                    run.touched.add(s["device_id"])
                except SimulationError as e:
                    msg = f"skipped: {e}"
                run.log.append(f"t+{time.time() - run.started_at:.0f}s  {msg}")
            remaining = run.started_at + run.duration_s - time.time()
            if remaining > 0:
                await asyncio.sleep(remaining)
            run.log.append(f"t+{time.time() - run.started_at:.0f}s  finished")
        except asyncio.CancelledError:
            run.log.append(f"t+{time.time() - run.started_at:.0f}s  stopped by user")
            self._restore(run)
            raise
        finally:
            run.done = True

    def _restore(self, run: Run) -> None:
        for dev in run.touched:
            try:
                sim_adapter(self.runtime, dev, run.org_id).restore()
            except SimulationError:
                pass

    def stop(self, factory_id: str) -> Run | None:
        run = self.runs.get(factory_id)
        if run and not run.done and run.task:
            run.task.cancel()
        return run
