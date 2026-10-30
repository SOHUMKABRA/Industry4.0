from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    summary: str = "",
    details: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> None:
    """Add an audit row to the current transaction (committed with the change)."""
    db.add(
        AuditLog(
            org_id=org_id or (user.org_id if user else None),
            user_id=user.id if user else None,
            user_email=user.email if user else "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:500],
            details=details or {},
        )
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {k: {"from": before.get(k), "to": v} for k, v in after.items() if before.get(k) != v}
