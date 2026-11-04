from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Alert, Factory, User
from app.services import audit
from app.telemetry.alerts import serialize

router = APIRouter(prefix="/alerts", tags=["alerts"])
Acker = Annotated[User, Depends(require(Perm.ALERT_ACK))]


def _out(a: Alert) -> dict:
    return serialize({c.name: getattr(a, c.name) for c in Alert.__table__.columns})


@router.get("")
def list_alerts(user: CurrentUser, db: DB, factory_id: str, state: str = Query(default="active", pattern="^(active|history|all)$"),
                limit: int = Query(default=200, le=1000)):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    q = select(Alert).where(Alert.org_id == user.org_id, Alert.factory_id == f.id)
    if state == "active":
        q = q.where(Alert.active.is_(True))
    elif state == "history":
        q = q.where(Alert.active.is_(False))
    return [_out(a) for a in db.scalars(q.order_by(Alert.raised_at.desc()).limit(limit))]


def _ack(db, request: Request, user: User, alerts: list[Alert]) -> int:
    now = datetime.now(UTC)
    rt = getattr(request.app.state, "telemetry", None)
    n = 0
    for a in alerts:
        if a.acked:
            continue
        a.acked, a.acked_by, a.acked_at, a.updated_at = True, user.email, now, now
        if rt:
            rt.alerts.mark_acked(a.id, user.email, now)
            rt.hub.publish_event(a.org_id, a.factory_id, {"type": "alert", "alert": _out(a)})
        n += 1
    return n


@router.post("/{alert_id}/ack")
def ack(alert_id: str, request: Request, user: Acker, db: DB):
    a = get_owned(db, Alert, alert_id, user, "Alert")
    if _ack(db, request, user, [a]):
        audit.record(db, user, "alert.ack", "alert", a.id, f"Acknowledged: {a.message[:200]}")
    db.commit()
    return _out(a)


@router.post("/ack-all")
def ack_all(factory_id: str, request: Request, user: Acker, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    alerts = db.scalars(select(Alert).where(Alert.factory_id == f.id, Alert.org_id == user.org_id, Alert.acked.is_(False))).all()
    n = _ack(db, request, user, list(alerts))
    if n:
        audit.record(db, user, "alert.ack", "factory", f.id, f"Acknowledged {n} alert(s)")
    db.commit()
    return {"acknowledged": n}
