from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm, has_perm, role_at_least
from app.models import Asset, AutomationExecution, AutomationRule, Factory, NotificationChannel, User
from app.services import audit

router = APIRouter(prefix="/automations", tags=["automation"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]


class ConditionItem(BaseModel):
    asset_id: str
    measurement: str = Field(min_length=1, max_length=64)
    operator: Literal["==", "!=", "<", "<=", ">", ">="]
    value: str = Field(min_length=1, max_length=200)


class Conditions(BaseModel):
    match: Literal["all", "any"] = "all"
    for_s: float = Field(default=0, ge=0, le=86400)
    items: list[ConditionItem] = Field(default_factory=list, max_length=20)


class Trigger(BaseModel):
    type: Literal["condition", "schedule"] = "condition"
    every_minutes: int | None = Field(default=None, ge=1, le=1440)
    daily_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] = Field(default_factory=lambda: list(range(7)))

    @model_validator(mode="after")
    def _check(self):
        if self.type == "schedule" and not (self.every_minutes or self.daily_at):
            raise ValueError("A schedule needs 'every N minutes' or 'daily at HH:MM'")
        if any(d < 0 or d > 6 for d in self.days):
            raise ValueError("days are 0 (Mon) … 6 (Sun)")
        return self


class Action(BaseModel):
    type: Literal["alert", "notify", "command", "delay"]
    severity: Literal["info", "warning", "alarm"] = "warning"
    message: str = Field(default="", max_length=300)
    channel_id: str | None = None
    asset_id: str | None = None
    control: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seconds: float = Field(default=0, ge=0, le=3600)


class RuleIn(BaseModel):
    factory_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    enabled: bool = False
    trigger: Trigger = Field(default_factory=Trigger)
    conditions: Conditions = Field(default_factory=Conditions)
    actions: list[Action] = Field(min_length=1, max_length=20)
    cooldown_s: int = Field(default=60, ge=0, le=86400)


class DryRunIn(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)  # "asset_id:measurement" -> value


def _validate(db, user: User, body: RuleIn) -> list[str]:
    """Return warnings; raise on errors."""
    f = get_owned(db, Factory, body.factory_id, user, "Factory")
    errors, warnings = [], []
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.factory_id == f.id))}
    if body.trigger.type == "condition" and not body.conditions.items:
        errors.append("A condition-triggered rule needs at least one condition")
    for i, c in enumerate(body.conditions.items, 1):
        a = assets.get(c.asset_id)
        if a is None:
            errors.append(f"Condition {i}: asset not in this factory")
        elif c.measurement not in {d["key"] for d in a.asset_type.telemetry}:
            errors.append(f"Condition {i}: {a.code} has no measurement '{c.measurement}'")
    for i, act in enumerate(body.actions, 1):
        if act.type == "notify":
            ch = db.get(NotificationChannel, act.channel_id) if act.channel_id else None
            if ch is None or ch.org_id != user.org_id:
                errors.append(f"Action {i}: choose a notification channel")
        if act.type == "command":
            a = assets.get(act.asset_id or "")
            ctl = next((c for c in a.asset_type.controls if c["key"] == act.control), None) if a else None
            if a is None:
                errors.append(f"Action {i}: command target must be an asset in this factory")
            elif ctl is None:
                errors.append(f"Action {i}: {a.code} has no control '{act.control}'")
            else:
                if not has_perm(user.role, Perm.CONTROL_EXECUTE) or not role_at_least(user.role, ctl.get("min_role", "operator")):
                    errors.append(f"Action {i}: your role can't issue '{ctl['label']}', so a rule you own can't either")
                if ctl.get("requires_approval"):
                    warnings.append(f"Action {i}: '{ctl['label']}' needs second-person approval; the rule will create a request and wait for a person")
                for p in ctl.get("params", []):
                    if p["key"] not in act.params:
                        errors.append(f"Action {i}: parameter '{p['label']}' is required")
        if act.type in ("alert", "notify") and not act.message:
            warnings.append(f"Action {i}: no message set; a default text will be used")
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "Rule is not valid", "fields": {str(i): e for i, e in enumerate(errors)}})
    return warnings


def _out(r: AutomationRule) -> dict[str, Any]:
    d = {c.name: getattr(r, c.name) for c in AutomationRule.__table__.columns}
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}


def _engine(request: Request):
    return getattr(request.app.state, "automation", None)


@router.get("")
def list_rules(factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    return [_out(r) for r in db.scalars(select(AutomationRule).where(AutomationRule.factory_id == f.id).order_by(AutomationRule.name))]


@router.post("/validate")
def validate(body: RuleIn, user: Writer, db: DB):
    return {"ok": True, "warnings": _validate(db, user, body)}


@router.post("", status_code=201)
def create_rule(body: RuleIn, request: Request, user: Writer, db: DB):
    warnings = _validate(db, user, body)
    r = AutomationRule(org_id=user.org_id, run_as_user_id=user.id, created_by=user.email, **body.model_dump(mode="json"))
    db.add(r)
    db.flush()
    audit.record(db, user, "automation.create", "automation", r.id, f"Created automation '{r.name}'", body.model_dump(mode="json"))
    db.commit()
    if (eng := _engine(request)):
        eng.reload()
    return {**_out(r), "warnings": warnings}


@router.put("/{rule_id}")
def update_rule(rule_id: str, body: RuleIn, request: Request, user: Writer, db: DB):
    r = get_owned(db, AutomationRule, rule_id, user, "Automation")
    warnings = _validate(db, user, body)
    for k, v in body.model_dump(mode="json").items():
        setattr(r, k, v)
    r.run_as_user_id = user.id  # the last editor owns the rule's permissions
    r.version += 1
    audit.record(db, user, "automation.update", "automation", r.id, f"Updated automation '{r.name}' (v{r.version}, {'enabled' if r.enabled else 'disabled'})",
                 body.model_dump(mode="json"))
    db.commit()
    if (eng := _engine(request)):
        eng.reload()
    return {**_out(r), "warnings": warnings}


@router.post("/{rule_id}/enabled")
def set_enabled(rule_id: str, request: Request, user: Writer, db: DB, enabled: bool = Query()):
    r = get_owned(db, AutomationRule, rule_id, user, "Automation")
    r.enabled = enabled
    r.version += 1
    audit.record(db, user, "automation.enable" if enabled else "automation.disable", "automation", r.id,
                 f"{'Enabled' if enabled else 'Disabled'} automation '{r.name}'")
    db.commit()
    if (eng := _engine(request)):
        eng.reload()
    return _out(r)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: str, request: Request, user: Writer, db: DB):
    r = get_owned(db, AutomationRule, rule_id, user, "Automation")
    audit.record(db, user, "automation.delete", "automation", r.id, f"Deleted automation '{r.name}'")
    db.delete(r)
    db.commit()
    if (eng := _engine(request)):
        eng.reload()
    return Response(status_code=204)


@router.post("/{rule_id}/dry-run")
async def dry_run(rule_id: str, body: DryRunIn, request: Request, user: Writer, db: DB):
    r = get_owned(db, AutomationRule, rule_id, user, "Automation")
    eng = _engine(request)
    if eng is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Automation engine is not running")
    rule = {c.name: getattr(r, c.name) for c in AutomationRule.__table__.columns}
    return await eng.dry_run(rule, body.overrides or None)


@router.get("/{rule_id}/executions")
def executions(rule_id: str, user: CurrentUser, db: DB, limit: int = Query(default=50, le=500)):
    r = get_owned(db, AutomationRule, rule_id, user, "Automation")
    rows = db.scalars(select(AutomationExecution).where(AutomationExecution.rule_id == r.id)
                      .order_by(AutomationExecution.started_at.desc()).limit(limit))
    return [{c.name: (getattr(x, c.name).isoformat() if hasattr(getattr(x, c.name), "isoformat") else getattr(x, c.name))
             for c in AutomationExecution.__table__.columns} for x in rows]
