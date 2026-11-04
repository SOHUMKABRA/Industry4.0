"""No-code automation engine.

A rule = trigger (live condition or schedule) + optional guard conditions +
ordered actions (alert, notify, command, delay). Rules are data; nothing
user-supplied is ever executed as code.

Safety
  * Conditions use fresh telemetry only: missing/stale values are false.
  * Commands go through the control engine as the rule's owner: same permission,
    limit, interlock, rate-limit, approval and verification rules as a human.
    Controls that require approval wait for a person.
  * Condition rules are edge-triggered (fire once when the condition becomes true
    and has held for `for_s`), re-arm when it becomes false, and respect a cooldown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.control.engine import OPS, TERMINAL, ControlEngine, _coerce
from app.models import Asset, AutomationExecution, AutomationRule, ControlCommand, Factory, User
from app.notify.service import Event, Notifier
from app.services import audit
from app.telemetry.runtime import TelemetryRuntime

log = logging.getLogger("twin.automation")

TICK_S = 1.0
RELOAD_S = 5.0
COMMAND_WAIT_S = 45.0


@dataclass
class RuleState:
    rule: dict[str, Any]
    since: float | None = None
    fired: bool = False
    last_fire: float = 0.0
    last_sched_key: str | None = None
    running: bool = False


@dataclass
class CondResult:
    ok: bool
    lines: list[str] = field(default_factory=list)
    first_value: Any = None


def _render(template: str, rule: dict[str, Any], detail: str, value: Any) -> str:
    try:
        return template.replace("{rule}", rule["name"]).replace("{detail}", detail).replace("{value}", str(value))
    except Exception:  # noqa: BLE001
        return template


class AutomationEngine:
    def __init__(self, runtime: TelemetryRuntime | None, control: ControlEngine, notifier: Notifier, session_factory: sessionmaker):
        self.runtime = runtime
        self.control = control
        self.notifier = notifier
        self.session_factory = session_factory
        self.rules: dict[str, RuleState] = {}
        self._task: asyncio.Task | None = None
        self._runs: set[asyncio.Task] = set()
        self._tz: dict[str, ZoneInfo] = {}
        self.stats = {"fired": 0, "skipped": 0}

    # ---------- lifecycle ----------
    async def start(self) -> None:
        await asyncio.to_thread(self.reload)
        self._task = asyncio.create_task(self._loop(), name="automation")

    async def stop(self) -> None:
        for t in [self._task, *self._runs]:
            if t:
                t.cancel()
        await asyncio.gather(*(t for t in [self._task, *self._runs] if t), return_exceptions=True)

    def reload(self) -> None:
        with self.session_factory() as db:
            rows = db.scalars(select(AutomationRule).where(AutomationRule.enabled.is_(True))).all()
            factories = {f.id: f.timezone for f in db.scalars(select(Factory))}
            fresh = {}
            for r in rows:
                d = {c.name: getattr(r, c.name) for c in AutomationRule.__table__.columns}
                cur = self.rules.get(r.id)
                if cur and cur.rule["version"] == r.version:
                    cur.rule = d
                    fresh[r.id] = cur
                else:
                    fresh[r.id] = RuleState(d)
            gone = set(self.rules) - set(fresh)
            for rid in gone:
                self._clear_rule_alert(rid)
            self.rules = fresh
            for fid, tz in factories.items():
                try:
                    self._tz[fid] = ZoneInfo(tz or "UTC")
                except Exception:  # noqa: BLE001
                    self._tz[fid] = ZoneInfo("UTC")

    async def _loop(self) -> None:
        last_reload = time.monotonic()
        while True:
            try:
                if time.monotonic() - last_reload > RELOAD_S:
                    await asyncio.to_thread(self.reload)
                    last_reload = time.monotonic()
                self.tick(time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("automation tick failed")
            await asyncio.sleep(TICK_S)

    # ---------- evaluation ----------
    def evaluate(self, rule: dict[str, Any], now: float, overrides: dict[str, Any] | None = None) -> CondResult:
        cond = rule.get("conditions") or {}
        items = cond.get("items") or []
        if not items:
            return CondResult(True, ["(no conditions)"])
        results, lines, first = [], [], None
        for it in items:
            key = f"{it['asset_id']}:{it['measurement']}"
            meta = self.runtime.assets.get(it["asset_id"]) if self.runtime else None
            code = meta.code if meta else it["asset_id"][:8]
            label = f"{code}.{it['measurement']} {it['operator']} {it['value']}"
            if overrides and key in overrides:
                actual, fresh = overrides[key], True
            else:
                lv = self.runtime.latest_value(it["asset_id"], it["measurement"]) if self.runtime else None
                d = meta.defs.get(it["measurement"], {}) if meta else {}
                max_age = max(3 * float(d.get("expected_interval_s", 5)), 6)
                fresh = lv is not None and now - lv.ts.timestamp() <= max_age
                actual = lv.value if lv else None
            if not fresh:
                results.append(False)
                lines.append(f"{label}: no fresh data (treated as false)")
                continue
            expected = _coerce(it["value"])
            try:
                ok = OPS[it["operator"]](float(actual) if isinstance(expected, float) else actual, expected)
            except (TypeError, ValueError):
                ok = False
            if first is None:
                first = actual
            results.append(ok)
            lines.append(f"{label}: actual {actual} → {'true' if ok else 'false'}")
        ok = all(results) if cond.get("match", "all") == "all" else any(results)
        return CondResult(ok, lines, first)

    def _schedule_due(self, rule: dict[str, Any], now: float) -> str | None:
        trig = rule.get("trigger") or {}
        tz = self._tz.get(rule["factory_id"], ZoneInfo("UTC"))
        local = datetime.fromtimestamp(now, tz)
        if trig.get("every_minutes"):
            n = int(trig["every_minutes"])
            slot = int(now // (n * 60))
            return f"every:{slot}"
        if trig.get("daily_at"):
            hh, mm = (int(x) for x in trig["daily_at"].split(":"))
            days = trig.get("days") or list(range(7))
            if local.weekday() in days and (local.hour, local.minute) == (hh, mm):
                return f"daily:{local.date()}"
        return None

    def tick(self, now: float) -> None:
        for rid, st in list(self.rules.items()):
            rule = st.rule
            ttype = (rule.get("trigger") or {}).get("type", "condition")
            if ttype == "schedule":
                key = self._schedule_due(rule, now)
                if key is None or key == st.last_sched_key or st.running:
                    continue
                if st.last_sched_key is None and (rule.get("trigger") or {}).get("every_minutes"):
                    st.last_sched_key = key  # don't fire immediately on (re)load; wait for the next slot
                    continue
                st.last_sched_key = key
                res = self.evaluate(rule, now)
                if not res.ok:
                    self.stats["skipped"] += 1
                    self._spawn(rule, "Scheduled run skipped: guard conditions false\n" + "\n".join(res.lines), res, skipped=True)
                    continue
                self._spawn(rule, "Schedule " + key + ("\n" + "\n".join(res.lines) if res.lines else ""), res)
                continue
            res = self.evaluate(rule, now)
            if res.ok:
                st.since = st.since or now
                held = now - st.since
                if not st.fired and held >= float((rule.get("conditions") or {}).get("for_s", 0)) and not st.running:
                    if now - st.last_fire < float(rule.get("cooldown_s", 60)):
                        continue
                    st.fired = True
                    st.last_fire = now
                    self._spawn(rule, "Condition true" + (f" for {held:.0f}s" if held >= 1 else "") + "\n" + "\n".join(res.lines), res)
            else:
                st.since = None
                if st.fired:
                    st.fired = False
                    self._clear_rule_alert(rid)

    # ---------- execution ----------
    def _clear_rule_alert(self, rule_id: str) -> None:
        if self.runtime:
            self.runtime.alerts.clear_external((rule_id, "automation", ""))

    def _spawn(self, rule: dict[str, Any], detail: str, res: CondResult, skipped: bool = False) -> None:
        st = self.rules.get(rule["id"])
        if st:
            st.running = True
        task = asyncio.get_running_loop().create_task(self.execute(rule, detail, res, dry_run=False, skipped=skipped))
        self._runs.add(task)
        task.add_done_callback(self._runs.discard)

    async def execute(self, rule: dict[str, Any], detail: str, res: CondResult, dry_run: bool,
                      skipped: bool = False) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        started = datetime.now(UTC)
        status = "dry_run" if dry_run else "succeeded"
        if skipped:
            status = "skipped"
        elif not dry_run:
            self.stats["fired"] += 1
        try:
            for i, a in enumerate([] if skipped else rule.get("actions") or []):
                step = await self._action(rule, a, detail, res, dry_run)
                step["index"] = i
                steps.append(step)
                if step["status"] == "failed" and not dry_run:
                    status = "partial" if any(s["status"] == "done" for s in steps) else "failed"
        except asyncio.CancelledError:
            status = "failed"
            steps.append({"type": "engine", "status": "failed", "detail": "Interrupted (platform stopping)"})
            raise
        finally:
            rec = await asyncio.to_thread(self._persist, rule, started, status, dry_run, detail, steps)
            st = self.rules.get(rule["id"])
            if st and not dry_run:
                st.running = False
        return rec

    async def _action(self, rule: dict[str, Any], a: dict[str, Any], detail: str, res: CondResult, dry: bool) -> dict[str, Any]:
        at = datetime.now(UTC).isoformat()
        t = a.get("type")
        if t == "delay":
            secs = float(a.get("seconds", 0))
            if not dry:
                await asyncio.sleep(secs)
            return {"type": t, "status": "done" if not dry else "would_run", "detail": f"Wait {secs:g}s", "at": at}
        if t == "alert":
            msg = _render(a.get("message") or "Automation '{rule}' triggered", rule, detail.split("\n")[0], res.first_value)
            sev = a.get("severity", "warning")
            if dry:
                return {"type": t, "status": "would_run", "detail": f"Would raise {sev}: {msg}", "at": at}
            first_asset = ((rule.get("conditions") or {}).get("items") or [{}])[0].get("asset_id")
            self.runtime.alerts.raise_external((rule["id"], "automation", ""), rule["org_id"], rule["factory_id"], asset_id=first_asset,
                                               kind="automation", severity=sev, message=msg, source="live")
            return {"type": t, "status": "done", "detail": f"Raised {sev}: {msg}", "at": at}
        if t == "notify":
            msg = _render(a.get("message") or "Automation '{rule}' triggered", rule, detail.split("\n")[0], res.first_value)
            if dry:
                return {"type": t, "status": "would_run", "detail": f"Would notify channel: {msg}", "at": at}
            ok = self.notifier.submit(Event(rule["org_id"], "automation", msg, {"rule": {"id": rule["id"], "name": rule["name"]},
                                                                                "detail": detail}, a.get("severity", "info"),
                                            channel_ids=[a["channel_id"]]))
            return {"type": t, "status": "done" if ok else "failed", "detail": ("Queued: " if ok else "Notifier not running: ") + msg, "at": at}
        if t == "command":
            return await self._command(rule, a, detail, dry, at)
        return {"type": t, "status": "failed", "detail": f"Unknown action '{t}'", "at": at}

    async def _command(self, rule: dict[str, Any], a: dict[str, Any], detail: str, dry: bool, at: str) -> dict[str, Any]:
        def go():
            with self.session_factory() as db:
                user = db.get(User, rule["run_as_user_id"])
                asset = db.get(Asset, a["asset_id"])
                if user is None or not user.is_active:
                    return {"status": "failed", "detail": "Rule owner account is missing or deactivated"}
                if asset is None:
                    return {"status": "failed", "detail": "Target asset no longer exists"}
                params = dict(a.get("params") or {})
                if dry:
                    plan = self.control.plan(db, user, asset, a["control"], params, True)
                    blocked = [f"{c.name}: {c.detail}" for c in plan.checks if not c.ok]
                    return {"status": "would_run" if plan.ok else "would_block",
                            "detail": f"{a['control']} on {asset.code}: " + ("all checks pass" if plan.ok else "; ".join(blocked))}
                cmd = self.control.request(db, user, asset, a["control"], params, True, f"Automation '{rule['name']}': {detail.splitlines()[0]}"[:500])
                return {"status": "pending", "command_id": cmd.id, "asset": asset.code, "cmd_status": cmd.status}

        r = await asyncio.to_thread(go)
        if dry or r["status"] == "failed":
            return {"type": "command", "at": at, **r}
        cid = r["command_id"]
        end = time.time() + COMMAND_WAIT_S
        status = r["cmd_status"]
        msg = ""
        while status not in TERMINAL and status != "PENDING_APPROVAL" and time.time() < end:
            await asyncio.sleep(0.5)

            def poll():
                with self.session_factory() as db:
                    c = db.get(ControlCommand, cid)
                    return (c.status, c.result_message, c.verified) if c else ("FAILED", "missing", False)

            status, msg, _ = await asyncio.to_thread(poll)
        if not msg:
            def final():
                with self.session_factory() as db:
                    c = db.get(ControlCommand, cid)
                    return c.result_message if c else ""
            msg = await asyncio.to_thread(final)
        ok = status in ("COMPLETED", "PENDING_APPROVAL")
        return {"type": "command", "at": at, "status": "done" if ok else "failed", "command_id": cid,
                "detail": f"{a['control']} on {r['asset']}: {status.replace('_', ' ').lower()}" + (f". {msg}" if msg else "")}

    def _persist(self, rule, started, status, dry, detail, steps) -> dict[str, Any]:
        with self.session_factory() as db:
            ex = AutomationExecution(org_id=rule["org_id"], rule_id=rule["id"], started_at=started, finished_at=datetime.now(UTC),
                                     status=status, dry_run=dry, trigger_detail=detail[:500], steps=steps)
            db.add(ex)
            if not dry and status != "skipped":
                r = db.get(AutomationRule, rule["id"])
                if r:
                    r.last_fired_at = started
                audit.record(db, None, "automation.run", "automation", rule["id"], f"Automation '{rule['name']}' ran: {status}",
                             {"steps": steps}, org_id=rule["org_id"])
            db.commit()
            out = {c.name: getattr(ex, c.name) for c in AutomationExecution.__table__.columns}
        if self.runtime:
            self.runtime.hub.publish_event(rule["org_id"], rule["factory_id"], {"type": "automation", "execution": _ser(out)})
        return _ser(out)

    async def dry_run(self, rule: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
        res = self.evaluate(rule, time.time(), overrides)
        detail = ("Conditions TRUE" if res.ok else "Conditions FALSE (actions shown for preview)") + "\n" + "\n".join(res.lines)
        return await self.execute(rule, detail, res, dry_run=True)


def _ser(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}
