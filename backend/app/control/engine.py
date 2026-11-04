"""Control engine: validated, audited, acknowledged and verified commands.

Lifecycle
  REQUESTED → VALIDATING → [PENDING_APPROVAL] → APPROVED → SENT → ACKNOWLEDGED → COMPLETED
  terminal failures: REJECTED, FAILED, TIMED_OUT, CANCELLED

Safety position
  * Supervisory only. PLC logic, safety relays and hardwired E-stops stay in charge;
    a PLC may refuse a command this engine sent, and that is reported, not hidden.
  * Fail closed: missing or stale interlock data blocks the command.
  * A device acknowledgement is not success. COMPLETED requires the expected
    feedback in fresh telemetry; otherwise TIMED_OUT ("state unverified").
  * Validation runs again right before sending (conditions may change while
    waiting for approval).
  * Commands interrupted by a restart are failed with "state unknown".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.permissions import Perm, has_perm, role_at_least
from app.models import Asset, AssetType, ControlCommand, Device, Interlock, User
from app.services import audit
from app.telemetry.runtime import TelemetryRuntime

log = logging.getLogger("twin.control")

TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "TIMED_OUT", "CANCELLED"}
ACTIVE = {"REQUESTED", "VALIDATING", "PENDING_APPROVAL", "APPROVED", "SENT", "ACKNOWLEDGED"}
PER_ASSET_MIN_INTERVAL_S = 2.0
PER_USER_PER_MINUTE = 20
OPS = {
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b, "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class Plan:
    checks: list[Check]
    control: dict[str, Any] | None
    device: Device | None
    point: str | None
    value: Any
    simulated: bool
    expected: Any
    feedback_measurement: str | None

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _coerce(v: str) -> Any:
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _matches(actual: Any, expected: Any, tolerance: float | None) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return str(actual).lower() == str(expected).lower()
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError):
        return str(actual) == str(expected)
    tol = tolerance if tolerance is not None else max(abs(e) * 0.05, 0.01)
    return abs(a - e) <= tol


class ControlEngine:
    def __init__(self, runtime: TelemetryRuntime | None, session_factory: sessionmaker):
        self.runtime = runtime
        self.session_factory = session_factory
        self._tasks: dict[str, asyncio.Future] = {}
        # The server's event loop; API handlers run in worker threads and hand execution to it.
        self.loop: asyncio.AbstractEventLoop | None = None
        self._user_hits: dict[str, deque] = defaultdict(deque)
        self._asset_last: dict[str, float] = {}

    # ---------- validation ----------
    def plan(self, db: Session, user: User, asset: Asset, control_key: str, params: dict[str, Any],
             confirm: bool, *, executing: bool = False, ignore_cmd: str | None = None) -> Plan:
        checks: list[Check] = []
        t: AssetType = asset.asset_type
        control = next((c for c in t.controls if c["key"] == control_key), None)

        # 1. permission
        if not has_perm(user.role, Perm.CONTROL_EXECUTE):
            checks.append(Check("Permission", False, f"Role '{user.role}' may not issue commands"))
        elif control and not role_at_least(user.role, control.get("min_role", "operator")):
            checks.append(Check("Permission", False, f"'{control['label']}' requires role {control.get('min_role')} or higher"))
        else:
            checks.append(Check("Permission", True, f"{user.email} ({user.role})"))

        # 2. capability
        if control is None:
            checks.append(Check("Capability", False, f"{t.name} has no control '{control_key}'"))
            return Plan(checks, None, None, None, None, False, None, None)
        checks.append(Check("Capability", True, f"{control['label']} ({control['kind']})"))

        # 3. parameters
        value: Any = None
        perr = []
        for p in control.get("params", []):
            raw = params.get(p["key"])
            if raw is None or raw == "":
                perr.append(f"{p['label']} is required")
                continue
            if p.get("type") in ("number", "integer"):
                try:
                    num = float(raw)
                except (TypeError, ValueError):
                    perr.append(f"{p['label']} must be a number")
                    continue
                if p.get("min") is not None and num < p["min"]:
                    perr.append(f"{p['label']} {num:g} is below minimum {p['min']:g}{' ' + p['unit'] if p.get('unit') else ''}")
                if p.get("max") is not None and num > p["max"]:
                    perr.append(f"{p['label']} {num:g} is above maximum {p['max']:g}{' ' + p['unit'] if p.get('unit') else ''}")
                params[p["key"]] = int(num) if p.get("type") == "integer" else num
            elif p.get("type") == "enum" and raw not in p.get("options", []):
                perr.append(f"{p['label']} must be one of {', '.join(p.get('options', []))}")
        unknown = set(params) - {p["key"] for p in control.get("params", [])}
        if unknown:
            perr.append(f"Unknown parameter(s): {', '.join(sorted(unknown))}")
        checks.append(Check("Parameters", not perr, "; ".join(perr) or ("within limits" if control.get("params") else "none required")))

        # 4. device & mapping
        device = mapping = None
        devices = db.scalars(select(Device).where(Device.asset_id == asset.id, Device.enabled.is_(True))).all()
        for d in devices:
            m = next((m for m in (d.control_mappings or []) if m.get("control") == control_key), None)
            if m:
                device, mapping = d, m
                break
        point = mapping.get("point") if mapping else None
        if device is None:
            checks.append(Check("Device", False, "No enabled device on this asset has a control mapping for this command"))
        else:
            ctx = self.runtime.devices.get(device.id) if self.runtime else None
            if ctx is None:
                checks.append(Check("Device", False, f"{device.name} is not running in the telemetry runtime"))
            elif not ctx.adapter.supports_write:
                checks.append(Check("Device", False, f"{ctx.adapter.name} does not support writes"))
            elif not self.runtime.device_online(ctx):
                checks.append(Check("Device", False, f"{device.name} is offline: equipment state can't be verified"))
            else:
                checks.append(Check("Device", True, f"{device.name} online via {device.protocol} → {point}"))
            if mapping and control.get("params"):
                pkey = mapping.get("param") or control["params"][0]["key"]
                pv = params.get(pkey)
                value = pv * float(mapping.get("scale", 1)) if isinstance(pv, (int, float)) else pv
            elif mapping:
                value = mapping.get("value", True)

        # 5. interlocks (fail closed)
        locks = db.scalars(select(Interlock).where(Interlock.asset_id == asset.id, Interlock.enabled.is_(True),
                                                   Interlock.control_key.in_([control_key, "*"]))).all()
        if not locks:
            checks.append(Check("Interlocks", True, "No software interlocks configured (PLC/hardwired safety still applies)"))
        for lk in locks:
            src = db.get(Asset, lk.source_asset_id)
            label = f"{src.code if src else '?'}.{lk.measurement} {lk.operator} {lk.value}"
            lv = self.runtime.latest_value(lk.source_asset_id, lk.measurement) if self.runtime else None
            sdef = next((d for d in (src.asset_type.telemetry if src else []) if d["key"] == lk.measurement), {})
            max_age = max(3 * float(sdef.get("expected_interval_s", 5)), 6)
            if lv is None:
                checks.append(Check(f"Interlock: {label}", False, f"No data for {label}. Blocked (fail closed). {lk.message}"))
                continue
            age = time.time() - lv.ts.timestamp()
            if age > max_age:
                checks.append(Check(f"Interlock: {label}", False, f"Data is {age:.0f}s old (stale). Blocked (fail closed). {lk.message}"))
                continue
            actual, expected = lv.value, _coerce(lk.value)
            try:
                ok = OPS[lk.operator](float(actual) if isinstance(expected, float) else actual, expected)
            except (TypeError, ValueError):
                ok = False
            checks.append(Check(f"Interlock: {label}", ok, f"Actual: {actual}" + ("" if ok else f". {lk.message or 'Condition not met'}")))

        # 6. rate limits / concurrency
        busy = db.scalar(select(ControlCommand.id).where(ControlCommand.asset_id == asset.id, ControlCommand.status.in_(ACTIVE),
                                                         ControlCommand.id != (ignore_cmd or "")))
        if busy and not executing:
            checks.append(Check("Concurrency", False, "Another command for this asset is still in progress"))
        elif not executing:
            since = time.time() - self._asset_last.get(asset.id, 0)
            hits = self._user_hits[user.id]
            while hits and time.time() - hits[0] > 60:
                hits.popleft()
            if since < PER_ASSET_MIN_INTERVAL_S:
                checks.append(Check("Rate limit", False, f"Wait {PER_ASSET_MIN_INTERVAL_S - since:.1f}s between commands to the same asset"))
            elif len(hits) >= PER_USER_PER_MINUTE:
                checks.append(Check("Rate limit", False, f"More than {PER_USER_PER_MINUTE} commands per minute"))
            else:
                checks.append(Check("Rate limit", True, "OK"))

        # 7. confirmation
        if control.get("requires_confirmation", True) and not confirm and not executing:
            checks.append(Check("Confirmation", False, "Explicit operator confirmation is required"))
        elif control.get("requires_confirmation", True):
            checks.append(Check("Confirmation", True, "Confirmed by operator"))

        fm = control.get("feedback_measurement")
        if control["kind"] == "setpoint" and control.get("params"):
            expected = params.get(control["params"][0]["key"])
        else:
            expected = control.get("feedback_value")
        return Plan(checks, control, device, point, value, bool(device and device.protocol == "simulated"), expected, fm)

    # ---------- lifecycle ----------
    def _event(self, cmd: ControlCommand, status: str, detail: str = "") -> None:
        now = datetime.now(UTC)
        cmd.status = status
        cmd.events = [*cmd.events, {"status": status, "at": now.isoformat(), "detail": detail}]
        if status == "APPROVED":
            cmd.approved_at = cmd.approved_at or now
        elif status == "SENT":
            cmd.sent_at = now
        elif status == "ACKNOWLEDGED":
            cmd.acked_at = now
        if status in TERMINAL:
            cmd.finished_at = now
            if detail:
                cmd.result_message = detail

    def _publish(self, cmd: ControlCommand) -> None:
        if self.runtime:
            self.runtime.hub.publish_event(cmd.org_id, cmd.factory_id, {"type": "command", "command": serialize(cmd)})

    def request(self, db: Session, user: User, asset: Asset, control_key: str, params: dict[str, Any], confirm: bool, reason: str) -> ControlCommand:
        cmd = ControlCommand(org_id=user.org_id, factory_id=asset.factory_id, asset_id=asset.id, control_key=control_key,
                             params=dict(params), status="REQUESTED", requested_by=user.email, reason=reason[:500], events=[])
        self._event(cmd, "REQUESTED", f"by {user.email}")
        self._event(cmd, "VALIDATING")
        plan = self.plan(db, user, asset, control_key, params, confirm)
        cmd.params = dict(params)
        cmd.checks = [c.as_dict() for c in plan.checks]
        cmd.control_label = plan.control["label"] if plan.control else control_key
        cmd.device_id = plan.device.id if plan.device else None
        cmd.simulated = plan.simulated
        db.add(cmd)
        db.flush()
        if not plan.ok:
            failed = [c for c in plan.checks if not c.ok]
            self._event(cmd, "REJECTED", "; ".join(f"{c.name}: {c.detail}" for c in failed))
            audit.record(db, user, "command.rejected", "asset", asset.id, f"{cmd.control_label} on {asset.code} rejected: {failed[0].detail}",
                         {"command_id": cmd.id, "checks": cmd.checks})
        else:
            self._asset_last[asset.id] = time.time()
            self._user_hits[user.id].append(time.time())
            if plan.control.get("requires_approval"):
                self._event(cmd, "PENDING_APPROVAL", "Second-person approval required")
                audit.record(db, user, "command.requested", "asset", asset.id, f"{cmd.control_label} on {asset.code} awaiting approval",
                             {"command_id": cmd.id, "params": cmd.params, "reason": reason})
            else:
                self._event(cmd, "APPROVED", "Validation passed")
                audit.record(db, user, "command.requested", "asset", asset.id, f"{cmd.control_label} on {asset.code} approved",
                             {"command_id": cmd.id, "params": cmd.params, "reason": reason, "simulated": cmd.simulated})
        db.commit()
        self._publish(cmd)
        if cmd.status == "APPROVED":
            self._spawn(cmd.id, user.id)
        return cmd

    def approve(self, db: Session, user: User, cmd: ControlCommand) -> ControlCommand:
        if cmd.status != "PENDING_APPROVAL":
            raise ValueError(f"Command is {cmd.status}, not awaiting approval")
        if not has_perm(user.role, Perm.CONTROL_APPROVE):
            raise PermissionError("Your role can't approve commands")
        if cmd.requested_by == user.email:
            raise PermissionError("A different person must approve (four-eyes principle)")
        cmd.approved_by = user.email
        self._event(cmd, "APPROVED", f"Approved by {user.email}")
        audit.record(db, user, "command.approved", "asset", cmd.asset_id, f"Approved {cmd.control_label}", {"command_id": cmd.id})
        db.commit()
        self._publish(cmd)
        requester = db.scalar(select(User).where(User.email == cmd.requested_by))
        self._spawn(cmd.id, requester.id if requester else user.id)
        return cmd

    def reject(self, db: Session, user: User, cmd: ControlCommand, why: str) -> ControlCommand:
        if cmd.status != "PENDING_APPROVAL":
            raise ValueError(f"Command is {cmd.status}, not awaiting approval")
        if not has_perm(user.role, Perm.CONTROL_APPROVE):
            raise PermissionError("Your role can't reject commands")
        self._event(cmd, "REJECTED", f"Rejected by {user.email}: {why or 'no reason given'}")
        audit.record(db, user, "command.rejected", "asset", cmd.asset_id, f"Approval refused for {cmd.control_label}", {"command_id": cmd.id})
        db.commit()
        self._publish(cmd)
        return cmd

    def cancel(self, db: Session, user: User, cmd: ControlCommand) -> ControlCommand:
        if cmd.status not in ("PENDING_APPROVAL", "APPROVED"):
            raise ValueError(f"A {cmd.status} command can no longer be cancelled")
        if cmd.requested_by != user.email and not has_perm(user.role, Perm.CONTROL_APPROVE):
            raise PermissionError("Only the requester or an approver can cancel")
        task = self._tasks.pop(cmd.id, None)
        if task:
            task.cancel()
        self._event(cmd, "CANCELLED", f"Cancelled by {user.email}")
        audit.record(db, user, "command.cancelled", "asset", cmd.asset_id, f"Cancelled {cmd.control_label}", {"command_id": cmd.id})
        db.commit()
        self._publish(cmd)
        return cmd

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _spawn(self, cmd_id: str, user_id: str) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and (self.loop is None or running is self.loop):
            self._tasks[cmd_id] = running.create_task(self._execute(cmd_id, user_id))
        elif self.loop is not None and self.loop.is_running():
            self._tasks[cmd_id] = asyncio.run_coroutine_threadsafe(self._execute(cmd_id, user_id), self.loop)
        else:
            # Never leave an approved command hanging without an executor.
            self._finish(cmd_id, "FAILED", "Control engine has no running executor; nothing was sent.")

    async def _execute(self, cmd_id: str, user_id: str) -> None:
        try:
            await self._run(cmd_id, user_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001 - every failure must end in a terminal state
            log.exception("command %s crashed", cmd_id)
            await asyncio.to_thread(self._finish, cmd_id, "FAILED", f"Internal error: {type(e).__name__}: {e}. Equipment state unknown; verify on site.")
        finally:
            self._tasks.pop(cmd_id, None)

    def _finish(self, cmd_id: str, status: str, detail: str, verified: bool = False) -> None:
        with self.session_factory() as db:
            cmd = db.get(ControlCommand, cmd_id)
            if cmd is None or cmd.status in TERMINAL:
                return
            cmd.verified = verified
            self._event(cmd, status, detail)
            asset = db.get(Asset, cmd.asset_id)
            audit.record(db, None, f"command.{status.lower()}", "asset", cmd.asset_id,
                         f"{cmd.control_label} on {asset.code if asset else '?'}: {status}", {"command_id": cmd.id, "detail": detail},
                         org_id=cmd.org_id)
            db.commit()
            self._publish(cmd)
            if status in ("FAILED", "TIMED_OUT") and self.runtime:
                self.runtime.alerts._raise(  # surfaces in the alert list
                    (cmd.id, "command", ""), cmd.org_id, cmd.factory_id, asset_id=cmd.asset_id, kind="command",
                    severity="warning", source="simulated" if cmd.simulated else "live",
                    message=f"Command {cmd.control_label} on {asset.code if asset else '?'} {status.replace('_', ' ').lower()}: {detail[:200]}")

    def _transition(self, cmd_id: str, status: str, detail: str = "") -> ControlCommand | None:
        with self.session_factory() as db:
            cmd = db.get(ControlCommand, cmd_id)
            if cmd is None or cmd.status in TERMINAL:
                return None
            self._event(cmd, status, detail)
            db.commit()
            self._publish(cmd)
            db.expunge(cmd)
            return cmd

    async def _run(self, cmd_id: str, user_id: str) -> None:
        # Re-validate immediately before sending: interlocks may have changed.
        def recheck():
            with self.session_factory() as db:
                cmd = db.get(ControlCommand, cmd_id)
                user = db.get(User, user_id)
                asset = db.get(Asset, cmd.asset_id) if cmd else None
                if cmd is None or cmd.status != "APPROVED" or asset is None or user is None:
                    return None, None
                plan = self.plan(db, user, asset, cmd.control_key, dict(cmd.params), True, executing=True, ignore_cmd=cmd.id)
                return plan, (cmd.control_label, asset.code)

        plan, _ = await asyncio.to_thread(recheck)
        if plan is None:
            return
        if not plan.ok:
            failed = [c for c in plan.checks if not c.ok]
            await asyncio.to_thread(self._finish, cmd_id, "REJECTED",
                                    "Re-check before sending failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failed))
            return
        before = self.runtime.latest_value(plan.device.asset_id, plan.feedback_measurement) if plan.feedback_measurement else None
        already = before is not None and plan.expected is not None and _matches(before.value, plan.expected, plan.control.get("feedback_tolerance"))
        await asyncio.to_thread(self._transition, cmd_id, "SENT", f"{plan.point} ← {plan.value!r}")
        try:
            ack = await self.runtime.write(plan.device.id, plan.point, plan.value)
        except Exception as e:  # noqa: BLE001
            await asyncio.to_thread(self._finish, cmd_id, "FAILED",
                                    f"Write failed: {type(e).__name__}: {e}. The command may not have reached the equipment.")
            return
        if not ack.accepted:
            await asyncio.to_thread(self._finish, cmd_id, "FAILED", f"Device refused: {ack.message}")
            return
        await asyncio.to_thread(self._transition, cmd_id, "ACKNOWLEDGED", ack.message)

        fm = plan.feedback_measurement
        if not fm or plan.expected is None:
            await asyncio.to_thread(self._finish, cmd_id, "COMPLETED",
                                    "Acknowledged by device. Outcome not verified: no feedback measurement configured.", False)
            return
        sent_at = time.time()
        timeout = float(plan.control.get("timeout_s", 15))
        tol = plan.control.get("feedback_tolerance")
        last = None
        while time.time() - sent_at < timeout:
            lv = self.runtime.latest_value(plan.device.asset_id, fm)
            if lv is not None and lv.ts.timestamp() >= sent_at - 0.5:
                last = lv.value
                if _matches(lv.value, plan.expected, tol):
                    note = " (equipment was already in this state)" if already else ""
                    await asyncio.to_thread(self._finish, cmd_id, "COMPLETED",
                                            f"Verified: {fm} = {lv.value} (expected {plan.expected}) after {time.time() - sent_at:.1f}s{note}", True)
                    return
            await asyncio.sleep(0.25)
        await asyncio.to_thread(self._finish, cmd_id, "TIMED_OUT",
                                f"Device acknowledged, but {fm} did not reach {plan.expected} within {timeout:.0f}s "
                                f"(last value: {last if last is not None else 'no fresh data'}). Actual equipment state unverified; check locally.")

    # ---------- startup ----------
    def recover(self) -> int:
        """Commands interrupted by a restart: the outcome is unknown, never assumed."""
        with self.session_factory() as db:
            stuck = db.scalars(select(ControlCommand).where(ControlCommand.status.in_(ACTIVE - {"PENDING_APPROVAL"}))).all()
            for cmd in stuck:
                self._event(cmd, "FAILED", "Platform restarted before completion. Actual equipment state unknown; verify on site.")
            db.commit()
            return len(stuck)


def serialize(cmd: ControlCommand) -> dict[str, Any]:
    out = {}
    for c in ControlCommand.__table__.columns:
        v = getattr(cmd, c.name)
        out[c.name] = v.isoformat() if isinstance(v, datetime) else v
    return out
