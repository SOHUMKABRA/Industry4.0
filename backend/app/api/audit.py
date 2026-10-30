from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.deps import DB, require
from app.core.permissions import Perm
from app.models import AuditLog, User
from app.schemas.devices import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    user: Annotated[User, Depends(require(Perm.AUDIT_READ))],
    db: DB,
    entity_id: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=200, le=1000),
):
    q = select(AuditLog).where(AuditLog.org_id == user.org_id)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    return db.scalars(q.order_by(AuditLog.at.desc()).limit(limit)).all()
