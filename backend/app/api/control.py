from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.control.engine import ControlEngine, serialize
from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, ControlCommand, Interlock, User
from app.services import audit

router = APIRouter(tags=["control"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]


def engine_of(request: Request) -> ControlEngine:
    eng = getattr(request.app.state, "control", None)
    if eng is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Control engine is not running")
    return eng


class CommandIn(BaseModel):
    control: str
    params: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    reason: str = Field(default="", max_length=500)


class Decision(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/assets/{asset_id}/commands/validate")
def validate_command(asset_id: str, body: CommandIn, request: Request, user: CurrentUser, db: DB):
    """Dry run: every check the real command would face, nothing is sent."""
    a = get_owned(db, Asset, asset_id, user, "Asset")
    plan = engine_of(request).plan(db, user, a, body.control, dict(body.params), body.confirm)
    return {"ok": plan.ok, "checks": [c.as_dict() for c in plan.checks], "simulated": plan.simulated,
            "requires_approval": bool(plan.control and plan.control.get("requires_approval"))}


@router.post("/assets/{asset_id}/commands", status_code=201)
def issue_command(asset_id: str, body: CommandIn, request: Request, user: CurrentUser, db: DB):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    cmd = engine_of(request).request(db, user, a, body.control, dict(body.params), body.confirm, body.reason)
    return serialize(cmd)


@router.get("/commands")
def list_commands(user: CurrentUser, db: DB, factory_id: str | None = None, asset_id: str | None = None,
                  status_: str | None = Query(default=None, alias="status"), limit: int = Query(default=100, le=500)):
    q = select(ControlCommand).where(ControlCommand.org_id == user.org_id)
    if factory_id:
        q = q.where(ControlCommand.factory_id == factory_id)
    if asset_id:
        q = q.where(ControlCommand.asset_id == asset_id)
    if status_:
        q = q.where(ControlCommand.status.in_(status_.split(",")))
    return [serialize(c) for c in db.scalars(q.order_by(ControlCommand.requested_at.desc()).limit(limit))]


@router.get("/commands/{cmd_id}")
def get_command(cmd_id: str, user: CurrentUser, db: DB):
    return serialize(get_owned(db, ControlCommand, cmd_id, user, "Command"))


def _decide(fn, cmd_id: str, request: Request, user: User, db, *args):
    cmd = get_owned(db, ControlCommand, cmd_id, user, "Command")
    try:
        return serialize(fn(db, user, cmd, *args))
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.post("/commands/{cmd_id}/approve")
def approve(cmd_id: str, request: Request, user: CurrentUser, db: DB):
    return _decide(engine_of(request).approve, cmd_id, request, user, db)


@router.post("/commands/{cmd_id}/reject")
def reject(cmd_id: str, body: Decision, request: Request, user: CurrentUser, db: DB):
    return _decide(engine_of(request).reject, cmd_id, request, user, db, body.reason)


@router.post("/commands/{cmd_id}/cancel")
def cancel(cmd_id: str, request: Request, user: CurrentUser, db: DB):
    return _decide(engine_of(request).cancel, cmd_id, request, user, db)


# ---------- interlocks ----------
class InterlockIn(BaseModel):
    control_key: str = Field(default="*", max_length=64)
    source_asset_id: str
    measurement: str = Field(min_length=1, max_length=64)
    operator: str = Field(pattern=r"^(==|!=|<|<=|>|>=)$")
    value: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=300)
    enabled: bool = True


def _interlock_out(i: Interlock, db) -> dict[str, Any]:
    src = db.get(Asset, i.source_asset_id)
    return {"id": i.id, "asset_id": i.asset_id, "control_key": i.control_key, "source_asset_id": i.source_asset_id,
            "source_code": src.code if src else None, "measurement": i.measurement, "operator": i.operator,
            "value": i.value, "message": i.message, "enabled": i.enabled}


def _check_interlock(db, user: User, asset: Asset, body: InterlockIn) -> None:
    src = get_owned(db, Asset, body.source_asset_id, user, "Source asset")
    if src.factory_id != asset.factory_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Source asset must be in the same factory")
    if body.measurement not in {d["key"] for d in src.asset_type.telemetry}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{src.code} has no measurement '{body.measurement}'")
    if body.control_key != "*" and body.control_key not in {c["key"] for c in asset.asset_type.controls}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{asset.code} has no control '{body.control_key}'")


@router.get("/assets/{asset_id}/interlocks")
def list_interlocks(asset_id: str, user: CurrentUser, db: DB):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    return [_interlock_out(i, db) for i in db.scalars(select(Interlock).where(Interlock.asset_id == a.id))]


@router.post("/assets/{asset_id}/interlocks", status_code=201)
def create_interlock(asset_id: str, body: InterlockIn, user: Writer, db: DB):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    _check_interlock(db, user, a, body)
    i = Interlock(org_id=user.org_id, asset_id=a.id, **body.model_dump())
    db.add(i)
    db.flush()
    audit.record(db, user, "interlock.create", "asset", a.id, f"Added interlock on {a.code}: {body.measurement} {body.operator} {body.value}")
    db.commit()
    return _interlock_out(i, db)


@router.put("/interlocks/{interlock_id}")
def update_interlock(interlock_id: str, body: InterlockIn, user: Writer, db: DB):
    i = get_owned(db, Interlock, interlock_id, user, "Interlock")
    a = db.get(Asset, i.asset_id)
    _check_interlock(db, user, a, body)
    for k, v in body.model_dump().items():
        setattr(i, k, v)
    audit.record(db, user, "interlock.update", "asset", a.id, f"Updated interlock on {a.code}", body.model_dump())
    db.commit()
    return _interlock_out(i, db)


@router.delete("/interlocks/{interlock_id}", status_code=204)
def delete_interlock(interlock_id: str, user: Writer, db: DB):
    i = get_owned(db, Interlock, interlock_id, user, "Interlock")
    audit.record(db, user, "interlock.delete", "asset", i.asset_id, f"Removed interlock {i.measurement} {i.operator} {i.value}")
    db.delete(i)
    db.commit()
    return Response(status_code=204)
