from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.crypto import encrypt_json
from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import NotificationChannel, NotificationDelivery, User
from app.notify.service import Event, Notifier
from app.services import audit

router = APIRouter(prefix="/notification-channels", tags=["notifications"])
Admin = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["webhook", "email"]
    enabled: bool = True
    alerts: bool = True
    min_severity: Literal["warning", "alarm"] = "warning"
    notify_clear: bool = False
    url: AnyHttpUrl | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    starttls: bool = True
    username: str | None = Field(default=None, max_length=255)
    from_addr: str | None = Field(default=None, max_length=255)
    to: str | None = Field(default=None, max_length=1000)
    # write-only
    secret: str | None = Field(default=None, max_length=500)
    password: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self):
        if self.type == "webhook" and not self.url:
            raise ValueError("A webhook needs a URL")
        if self.type == "email" and not (self.host and self.from_addr and self.to):
            raise ValueError("E-mail needs SMTP host, from address and recipients")
        return self

    def config(self) -> dict[str, Any]:
        if self.type == "webhook":
            return {"url": str(self.url)}
        return {"host": self.host, "port": self.port, "starttls": self.starttls, "username": self.username or "",
                "from": self.from_addr, "to": self.to}


def _out(c: NotificationChannel) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "type": c.type, "enabled": c.enabled, "alerts": c.alerts, "min_severity": c.min_severity,
            "notify_clear": c.notify_clear, "config": c.config, "has_secret": bool(c.secrets_encrypted)}


def _notifier(request: Request) -> Notifier:
    n = getattr(request.app.state, "notifier", None)
    if n is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Notifier is not running")
    return n


@router.get("")
def list_channels(user: CurrentUser, db: DB):
    return [_out(c) for c in db.scalars(select(NotificationChannel).where(NotificationChannel.org_id == user.org_id).order_by(NotificationChannel.name))]


def _apply(c: NotificationChannel, body: ChannelIn) -> None:
    c.name, c.type, c.enabled, c.alerts = body.name, body.type, body.enabled, body.alerts
    c.min_severity, c.notify_clear, c.config = body.min_severity, body.notify_clear, body.config()
    secrets = {k: v for k, v in {"secret": body.secret, "password": body.password}.items() if v}
    if secrets:
        c.secrets_encrypted = encrypt_json(secrets)


@router.post("", status_code=201)
def create_channel(body: ChannelIn, user: Admin, db: DB):
    c = NotificationChannel(org_id=user.org_id)
    _apply(c, body)
    db.add(c)
    db.flush()
    audit.record(db, user, "channel.create", "notification_channel", c.id, f"Created {c.type} channel '{c.name}'")
    db.commit()
    return _out(c)


@router.put("/{channel_id}")
def update_channel(channel_id: str, body: ChannelIn, user: Admin, db: DB):
    c = get_owned(db, NotificationChannel, channel_id, user, "Channel")
    _apply(c, body)
    audit.record(db, user, "channel.update", "notification_channel", c.id, f"Updated channel '{c.name}'")
    db.commit()
    return _out(c)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: str, user: Admin, db: DB):
    c = get_owned(db, NotificationChannel, channel_id, user, "Channel")
    audit.record(db, user, "channel.delete", "notification_channel", c.id, f"Deleted channel '{c.name}'")
    db.delete(c)
    db.commit()
    return Response(status_code=204)


@router.post("/{channel_id}/test")
async def test_channel(channel_id: str, request: Request, user: Admin, db: DB):
    import asyncio

    c = get_owned(db, NotificationChannel, channel_id, user, "Channel")
    ev = Event(user.org_id, "test", f"Test notification from {user.email}", {"note": "If you can read this, the channel works."},
               "info", channel_ids=[c.id])
    results = await asyncio.to_thread(_notifier(request).deliver_now, ev)
    return results[0] if results else {"status": "failed", "detail": "Channel disabled"}


@router.get("/{channel_id}/deliveries")
def deliveries(channel_id: str, user: CurrentUser, db: DB):
    c = get_owned(db, NotificationChannel, channel_id, user, "Channel")
    rows = db.scalars(select(NotificationDelivery).where(NotificationDelivery.channel_id == c.id).order_by(NotificationDelivery.at.desc()).limit(100))
    return [{"id": d.id, "at": d.at.isoformat(), "event": d.event, "subject": d.subject, "status": d.status,
             "attempts": d.attempts, "detail": d.detail} for d in rows]
