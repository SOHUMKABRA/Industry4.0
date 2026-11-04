"""Demo content for Phase 6: notification channel, automations, simulation drills.

Idempotent (by name); only touches the demo organization.
"""

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_json
from app.models import Asset, AutomationRule, Device, Factory, NotificationChannel, Organization, SimulationScenario, User
from app.seed.demo import DEMO_SLUG
from app.services import audit

LAB_INBOX = os.environ.get("LAB_INBOX_URL", "http://127.0.0.1:8090/hooks/inbox")
LAB_SECRET = os.environ.get("LAB_WEBHOOK_SECRET", "lab-demo-secret")


def _local_tz() -> str:
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def ensure_phase6_demo(db: Session) -> list[str]:
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_SLUG))
    if org is None:
        return []
    f = db.scalar(select(Factory).where(Factory.org_id == org.id).order_by(Factory.created_at))
    if f is None:
        return []
    done: list[str] = []
    if f.timezone == "UTC" and _local_tz() != "UTC":
        f.timezone = _local_tz()
        done.append(f"timezone {f.timezone}")
    a = {x.code: x for x in db.scalars(select(Asset).where(Asset.factory_id == f.id))}
    engineer = db.scalar(select(User).where(User.org_id == org.id, User.role == "engineer")) or \
        db.scalar(select(User).where(User.org_id == org.id, User.role == "admin"))

    ch = db.scalar(select(NotificationChannel).where(NotificationChannel.org_id == org.id, NotificationChannel.name == "Lab webhook inbox"))
    if ch is None:
        ch = NotificationChannel(org_id=org.id, name="Lab webhook inbox", type="webhook", config={"url": LAB_INBOX},
                                 secrets_encrypted=encrypt_json({"secret": LAB_SECRET}), alerts=True, min_severity="alarm", notify_clear=True)
        db.add(ch)
        db.flush()
        done.append("channel Lab webhook inbox")

    def cond(code, m, op, v):
        return {"asset_id": a[code].id, "measurement": m, "operator": op, "value": str(v)}

    rules = [
        {"name": "Shrink tunnel overheating", "enabled": True,
         "description": "TT-301 above 80 °C for 10 s: raise an alarm and tell the maintenance system.",
         "trigger": {"type": "condition", "days": list(range(7))},
         "conditions": {"match": "all", "for_s": 10, "items": [cond("TT-301", "temp", ">", 80)]},
         "actions": [{"type": "alert", "severity": "alarm", "message": "Shrink tunnel overheating ({value} °C): check heater controller"},
                     {"type": "notify", "channel_id": ch.id, "severity": "alarm", "message": "Shrink tunnel TT-301 at {value} °C (rule: {rule})"}],
         "cooldown_s": 300, "codes": ["TT-301"]},
        {"name": "Coolant overheat: start coolant pump", "enabled": True,
         "description": "TT-101 coolant above 80 °C for 5 s: start PMP-401 (through all interlocks) and notify.",
         "trigger": {"type": "condition", "days": list(range(7))},
         "conditions": {"match": "all", "for_s": 5, "items": [cond("TT-101", "temp", ">", 80)]},
         "actions": [{"type": "command", "asset_id": a["PMP-401"].id, "control": "start", "params": {}},
                     {"type": "notify", "channel_id": ch.id, "severity": "warning", "message": "Coolant {value} °C: {rule} requested PMP-401 start"}],
         "cooldown_s": 120, "codes": ["TT-101", "PMP-401"]},
        {"name": "Packing conveyor stopped while line runs", "enabled": True,
         "description": "CV-301 stopped or faulted for 20 s while LINE-3 is running.",
         "trigger": {"type": "condition", "days": list(range(7))},
         "conditions": {"match": "all", "for_s": 20, "items": [cond("CV-301", "state", "!=", "running"), cond("LINE-3", "state", "==", "running")]},
         "actions": [{"type": "alert", "severity": "warning", "message": "Packing conveyor CV-301 not running while Line 3 is running"}],
         "cooldown_s": 600, "codes": ["CV-301", "LINE-3"]},
        {"name": "Shift start notice", "enabled": True,
         "description": "06:00 Monday–Saturday: notify that the daily report is ready.",
         "trigger": {"type": "schedule", "daily_at": "06:00", "days": [0, 1, 2, 3, 4, 5]},
         "conditions": {"match": "all", "for_s": 0, "items": []},
         "actions": [{"type": "notify", "channel_id": ch.id, "severity": "info", "message": "Shift starting at Riverside Plant: yesterday's report is available"}],
         "cooldown_s": 60, "codes": []},
    ]
    have = set(db.scalars(select(AutomationRule.name).where(AutomationRule.factory_id == f.id)))
    for r in rules:
        codes = r.pop("codes")
        if r["name"] in have or engineer is None or any(c not in a for c in codes):
            continue
        db.add(AutomationRule(org_id=org.id, factory_id=f.id, run_as_user_id=engineer.id, created_by="system", **r))
        done.append(f"automation {r['name']}")

    dev = {d.name: d for d in db.scalars(select(Device).where(Device.factory_id == f.id, Device.protocol == "simulated", Device.enabled.is_(True)))}
    scenarios = [
        ("Line 1 motor overload", "MTR-101 current and winding temperature climb past alarm limits.",
         [("MTR-101 drive simulator", 0, "set", "current", 23.5, 30), ("MTR-101 drive simulator", 10, "set", "current", 26.8, 40),
          ("MTR-101 drive simulator", 15, "set", "winding_temp", 113, 40)]),
        ("Conveyor fault drill", "CV-102 reports a fault for 40 s, then recovers.",
         [("CV-102 simulator", 0, "set", "state", "fault", 40)]),
        ("Sensor dropout drill", "TT-301 stops reporting for 45 s: communication-loss alert and stale values.",
         [("TT-301 simulator", 0, "offline", None, None, 45)]),
    ]
    have_s = set(db.scalars(select(SimulationScenario.name).where(SimulationScenario.factory_id == f.id)))
    for name, desc, steps in scenarios:
        if name in have_s or any(s[0] not in dev for s in steps):
            continue
        db.add(SimulationScenario(org_id=org.id, factory_id=f.id, name=name, description=desc, created_by="system",
                                  steps=[{"at_s": at, "device_id": dev[d].id, "action": act, "point": pt, "value": v, "duration_s": dur}
                                         for d, at, act, pt, v, dur in steps]))
        done.append(f"scenario {name}")
    if done:
        audit.record(db, None, "demo.upgrade", "organization", org.id, "Phase 6 demo content: " + ", ".join(done), org_id=org.id)
    db.commit()
    return done
