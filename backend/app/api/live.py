"""Live telemetry: WebSocket stream, snapshot and history."""

import asyncio
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm, has_perm
from app.models import Asset, Dashboard, Factory, User
from app.schemas.scenes import DashboardIn, DashboardOut, DashboardPatch
from app.services import audit
from app.telemetry.hub import FLUSH_INTERVAL_S, Subscriber
from app.telemetry.runtime import TelemetryRuntime, history

log = logging.getLogger("twin.live")
router = APIRouter(tags=["live"])

TICKET_TTL_S = 30
_tickets: dict[str, tuple[str, str, float]] = {}  # ticket -> (user_id, org_id, expires)


def runtime_of(request_or_ws) -> TelemetryRuntime | None:
    return getattr(request_or_ws.app.state, "telemetry", None)


@router.post("/live/ticket")
def ws_ticket(user: CurrentUser):
    """Short-lived single-use ticket so the JWT never appears in a WebSocket URL."""
    now = time.time()
    for t, (_, _, exp) in list(_tickets.items()):
        if exp < now:
            _tickets.pop(t, None)
    t = secrets.token_urlsafe(24)
    _tickets[t] = (user.id, user.org_id, now + TICKET_TTL_S)
    return {"ticket": t, "expires_in": TICKET_TTL_S}


@router.get("/live/snapshot")
def snapshot(request: Request, factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    rt = runtime_of(request)
    if rt is None:
        return {"points": [], "devices": [], "running": False}
    return rt.snapshot(user.org_id, f.id)


@router.get("/assets/{asset_id}/history")
def asset_history(
    asset_id: str, user: CurrentUser, db: DB, measurement: str,
    minutes: int = Query(default=60, ge=1, le=1440), buckets: int = Query(default=120, ge=2, le=1000),
):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    until = datetime.now(UTC)
    since = until - timedelta(minutes=minutes)
    return {"asset_id": a.id, "measurement": measurement, "from": int(since.timestamp() * 1000),
            "to": int(until.timestamp() * 1000), "points": history(db, a.id, measurement, since, until, buckets)}


@router.websocket("/live/ws")
async def live_ws(ws: WebSocket, ticket: str = ""):
    entry = _tickets.pop(ticket, None)
    if entry is None or entry[2] < time.time():
        await ws.close(code=4401, reason="invalid or expired ticket")
        return
    user_id, org_id, _ = entry
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            await ws.close(code=4401)
            return
    rt = runtime_of(ws)
    await ws.accept()
    sub = Subscriber(org_id=org_id)
    if rt:
        rt.hub.add(sub)

    async def sender():
        last_beat = 0.0
        while True:
            try:
                await asyncio.wait_for(sub.wake.wait(), timeout=1.0)
            except TimeoutError:
                pass
            frames = sub.take()
            if frames:
                await ws.send_text(json.dumps({"type": "telemetry", "points": frames}))
            now = time.time()
            if now - last_beat >= 2 and rt and sub.factory_id:
                last_beat = now
                await ws.send_text(json.dumps({"type": "heartbeat", "server_ts": int(now * 1000),
                                               "devices": rt.device_states(org_id, sub.factory_id), "running": rt.running}))
            await asyncio.sleep(FLUSH_INTERVAL_S)

    send_task = asyncio.create_task(sender())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "subscribe":
                fid = str(msg.get("factory_id", ""))
                with SessionLocal() as db:
                    f = db.get(Factory, fid)
                if f is None or f.org_id != org_id:
                    await ws.send_text(json.dumps({"type": "error", "message": "Factory not found"}))
                    continue
                sub.factory_id = fid
                sub.asset_ids = set(msg["asset_ids"]) if msg.get("asset_ids") else None
                sub.pending.clear()
                snap = rt.snapshot(org_id, fid) if rt else {"points": [], "devices": [], "running": False}
                await ws.send_text(json.dumps({"type": "snapshot", "factory_id": fid, **snap}))
            elif kind == "ping":
                await ws.send_text(json.dumps({"type": "pong", "t": msg.get("t")}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        log.exception("websocket error")
    finally:
        send_task.cancel()
        if rt:
            rt.hub.remove(sub)


# ---------- dashboards ----------
DashWriter = Annotated[User, Depends(require(Perm.READ))]


def _can_edit(user: User, d: Dashboard) -> None:
    """Anyone can build dashboards; only the author or configurers change them."""
    if d.created_by != user.email and not has_perm(user.role, Perm.FACTORY_WRITE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the dashboard's author or an engineer can change it")


def _check_widgets(db, user: User, factory_id: str, widgets) -> None:
    ids = {w.asset_id for w in widgets if w.asset_id}
    if ids:
        ok = set(db.scalars(select(Asset.id).where(Asset.id.in_(ids), Asset.org_id == user.org_id, Asset.factory_id == factory_id)))
        if ids - ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Widget references an asset outside this factory")


@router.get("/dashboards", response_model=list[DashboardOut])
def list_dashboards(factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    return db.scalars(select(Dashboard).where(Dashboard.factory_id == f.id).order_by(Dashboard.created_at)).all()


@router.post("/dashboards", response_model=DashboardOut, status_code=201)
def create_dashboard(body: DashboardIn, user: DashWriter, db: DB):
    f = get_owned(db, Factory, body.factory_id, user, "Factory")
    _check_widgets(db, user, f.id, body.widgets)
    d = Dashboard(org_id=user.org_id, factory_id=f.id, name=body.name,
                  widgets=[w.model_dump() for w in body.widgets], created_by=user.email)
    db.add(d)
    db.flush()
    audit.record(db, user, "dashboard.create", "dashboard", d.id, f"Created dashboard {d.name}")
    db.commit()
    return d


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardOut)
def update_dashboard(dashboard_id: str, body: DashboardPatch, user: DashWriter, db: DB):
    d = get_owned(db, Dashboard, dashboard_id, user, "Dashboard")
    _can_edit(user, d)
    if body.name is not None:
        d.name = body.name
    if body.widgets is not None:
        _check_widgets(db, user, d.factory_id, body.widgets)
        d.widgets = [w.model_dump() for w in body.widgets]
    audit.record(db, user, "dashboard.update", "dashboard", d.id, f"Updated dashboard {d.name}")
    db.commit()
    return d


@router.delete("/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(dashboard_id: str, user: DashWriter, db: DB):
    d = get_owned(db, Dashboard, dashboard_id, user, "Dashboard")
    _can_edit(user, d)
    audit.record(db, user, "dashboard.delete", "dashboard", d.id, f"Deleted dashboard {d.name}")
    db.delete(d)
    db.commit()
    return Response(status_code=204)
