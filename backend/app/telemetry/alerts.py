"""Server-side alert engine.

Evaluated on every accepted telemetry value and on device connectivity changes:
  limit  — value beyond warn/alarm limits (from the asset type, overridable per asset)
  state  — equipment reports fault / emergency_stop / tripped
  comm   — a data source stopped reporting
One active alert per (asset or device, kind, measurement); escalation updates it,
clearing uses a deadband to avoid flapping. Writes are queued and flushed in
batches by the runtime; changes are pushed to WebSocket subscribers immediately.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert
from app.models.base import new_id

log = logging.getLogger("twin.alerts")

FAULT_STATES = {"fault": "Equipment fault", "emergency_stop": "Emergency stop active", "tripped": "E-stop circuit tripped"}
# Alarm-flood/chatter suppression (ISA-18.2 style): a limit must be exceeded for
# ON_DELAY before an alert is raised and be back inside the deadband for OFF_DELAY
# before it clears. Equipment fault states raise immediately.
DEADBAND_FRACTION = 0.02
ON_DELAY_S = 3.0
OFF_DELAY_S = 10.0
STATE_OFF_DELAY_S = 3.0


@dataclass
class AssetMeta:
    asset_id: str
    org_id: str
    factory_id: str
    code: str
    name: str
    defs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ActiveAlert:
    id: str
    severity: str
    raised_at: datetime
    acked: bool = False
    record: dict[str, Any] = field(default_factory=dict)


def _limit_state(d: dict[str, Any], v: float) -> tuple[str | None, float | None, str]:
    """Return (severity, threshold, direction)."""
    for sev, lo_key, hi_key in (("alarm", "alarm_low", "alarm_high"), ("warning", "warn_low", "warn_high")):
        hi, lo = d.get(hi_key), d.get(lo_key)
        if hi is not None and v >= hi:
            return sev, hi, "high"
        if lo is not None and v <= lo:
            return sev, lo, "low"
    return None, None, ""


def _within_deadband(d: dict[str, Any], v: float) -> bool:
    """True when v is inside all limits by a margin (so a cleared alert stays cleared)."""
    for key in ("warn_high", "alarm_high"):
        lim = d.get(key)
        if lim is not None and v > lim - max(abs(lim) * DEADBAND_FRACTION, 1e-9):
            return False
    for key in ("warn_low", "alarm_low"):
        lim = d.get(key)
        if lim is not None and v < lim + max(abs(lim) * DEADBAND_FRACTION, 1e-9):
            return False
    return True


class AlertEngine:
    def __init__(self, publish: Callable[[str, str, dict[str, Any]], None]):
        self.publish = publish  # (org_id, factory_id, alert_dict)
        self.active: dict[tuple[str, str, str], ActiveAlert] = {}
        self._ops: list[tuple[str, dict[str, Any]]] = []
        self._pending_raise: dict[tuple, tuple[str, float]] = {}
        self._pending_clear: dict[tuple, float] = {}
        self.stats = {"raised": 0, "cleared": 0}

    # ---------- state ----------
    def load_active(self, db: Session) -> int:
        for a in db.scalars(select(Alert).where(Alert.active.is_(True))):
            key = (a.asset_id or a.device_id or "", a.kind, a.measurement or "")
            rec = {c.name: getattr(a, c.name) for c in Alert.__table__.columns}
            self.active[key] = ActiveAlert(a.id, a.severity, a.raised_at, a.acked, rec)
        return len(self.active)

    def _emit(self, rec: dict[str, Any]) -> None:
        self.publish(rec["org_id"], rec["factory_id"], serialize(rec))

    def _raise(self, key, meta_org: str, factory_id: str, **fields) -> None:
        now = datetime.now(UTC)
        cur = self.active.get(key)
        if cur is None:
            rec = {"id": new_id(), "org_id": meta_org, "factory_id": factory_id, "active": True, "acked": False,
                   "acked_by": None, "acked_at": None, "raised_at": now, "updated_at": now, "cleared_at": None,
                   "value_num": None, "value_text": None, "threshold": None, "device_id": None, "asset_id": None,
                   "measurement": None, "source": "live", **fields}
            self.active[key] = ActiveAlert(rec["id"], rec["severity"], now, False, rec)
            self._ops.append(("insert", dict(rec)))
            self.stats["raised"] += 1
            self._emit(rec)
            return
        rec = cur.record
        escalated = fields.get("severity") == "alarm" and cur.severity != "alarm"
        changed = escalated or fields.get("message") != rec.get("message")
        rec.update(fields, updated_at=now)
        if escalated:
            rec.update(acked=False, acked_by=None, acked_at=None)
            cur.acked = False
        cur.severity = rec["severity"]
        if changed:
            self._ops.append(("update", {"id": cur.id, **{k: rec[k] for k in ("severity", "message", "value_num", "value_text",
                                                                              "threshold", "updated_at", "acked", "acked_by", "acked_at")}}))
            self._emit(rec)

    def _clear(self, key) -> None:
        cur = self.active.pop(key, None)
        if cur is None:
            return
        now = datetime.now(UTC)
        cur.record.update(active=False, cleared_at=now, updated_at=now)
        self._ops.append(("update", {"id": cur.id, "active": False, "cleared_at": now, "updated_at": now}))
        self.stats["cleared"] += 1
        self._emit(cur.record)

    def mark_acked(self, alert_id: str, by: str, at: datetime) -> None:
        for a in self.active.values():
            if a.id == alert_id:
                a.acked = True
                a.record.update(acked=True, acked_by=by, acked_at=at)

    # ---------- evaluation ----------
    def _debounced_clear(self, key, now: float, delay: float) -> None:
        if key not in self.active:
            self._pending_clear.pop(key, None)
            return
        since = self._pending_clear.setdefault(key, now)
        if now - since >= delay:
            self._pending_clear.pop(key, None)
            self._clear(key)

    def evaluate(self, meta: AssetMeta, measurement: str, value: Any, source: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        d = meta.defs.get(measurement)
        if d is None:
            return
        label = d.get("label") or measurement
        if isinstance(value, str) and measurement in ("state", "estop_status", "run_mode"):
            key = (meta.asset_id, "state", measurement)
            if value in FAULT_STATES:
                self._pending_clear.pop(key, None)
                self._raise(key, meta.org_id, meta.factory_id, asset_id=meta.asset_id, kind="state", measurement=measurement,
                            severity="alarm", value_text=value, source=source,
                            message=f"{meta.code} {meta.name}: {FAULT_STATES[value]}")
            else:
                self._debounced_clear(key, now, STATE_OFF_DELAY_S)
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        key = (meta.asset_id, "limit", measurement)
        sev, threshold, direction = _limit_state(d, float(value))
        unit = f" {d['unit']}" if d.get("unit") else ""
        if sev:
            self._pending_clear.pop(key, None)
            cur = self.active.get(key)
            pend = self._pending_raise.get(key)
            # Escalation of an existing alert is immediate; new alerts wait for the on-delay.
            if cur is None or (sev == "alarm" and cur.severity != "alarm"):
                if cur is None:
                    if pend is None or (sev == "alarm" and pend[0] != "alarm"):
                        self._pending_raise[key] = (sev, now if pend is None else pend[1])
                        pend = self._pending_raise[key]
                    if now - pend[1] < ON_DELAY_S:
                        return
                    self._pending_raise.pop(key, None)
            word = "above" if direction == "high" else "below"
            self._raise(key, meta.org_id, meta.factory_id, asset_id=meta.asset_id, kind="limit", measurement=measurement,
                        severity=sev, value_num=float(value), threshold=threshold, source=source,
                        message=f"{meta.code} {label} {value:g}{unit} is {word} {'alarm' if sev == 'alarm' else 'warning'} limit {threshold:g}{unit}")
        else:
            self._pending_raise.pop(key, None)
            if key in self.active and _within_deadband(d, float(value)):
                self._debounced_clear(key, now, OFF_DELAY_S)
            else:
                self._pending_clear.pop(key, None)

    def device_comm(self, org_id: str, factory_id: str, device_id: str, asset_id: str | None, name: str, online: bool, source: str) -> None:
        key = (device_id, "comm", "")
        if online:
            if key in self.active:
                self._clear(key)
        else:
            self._raise(key, org_id, factory_id, device_id=device_id, asset_id=asset_id, kind="comm", severity="warning",
                        source=source, message=f"Communication lost: {name}. Values from this source are stale.")

    def raise_external(self, key: tuple, org_id: str, factory_id: str, **fields) -> None:
        """Raise/update an alert owned by another subsystem (automation, control)."""
        self._raise(key, org_id, factory_id, **fields)

    def clear_external(self, key: tuple) -> None:
        self._clear(key)

    def device_removed(self, device_id: str) -> None:
        self._clear((device_id, "comm", ""))

    # ---------- persistence ----------
    def flush(self, db: Session) -> int:
        if not self._ops:
            return 0
        ops, self._ops = self._ops, []
        for kind, data in ops:
            if kind == "insert":
                db.add(Alert(**{k: v for k, v in data.items() if k in Alert.__table__.columns}))
            else:
                a = db.get(Alert, data["id"])
                if a is None:
                    db.flush()
                    a = db.get(Alert, data["id"])
                if a is not None:
                    for k, v in data.items():
                        if k != "id":
                            setattr(a, k, v)
        db.commit()
        return len(ops)


def serialize(rec: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in rec.items():
        out[k] = v.isoformat() if isinstance(v, datetime) else v
    return out
