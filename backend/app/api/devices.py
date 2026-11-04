import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.adapters.base import AdapterError, DeviceAdapter
from app.adapters.registry import get_adapter_class, list_protocols
from app.core.crypto import decrypt_json, encrypt_json
from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, Device, DeviceTemplate, Factory, User
from app.models.base import utcnow
from app.schemas.devices import (
    ControlMapping,
    DeviceIn,
    DeviceOut,
    DevicePatch,
    DiscoveredPoint,
    PointMapping,
    ProtocolOut,
    TemplateIn,
    TemplateOut,
    TestResult,
)
from app.services import audit

router = APIRouter(tags=["devices"])
Writer = Annotated[User, Depends(require(Perm.DEVICE_WRITE))]
Tester = Annotated[User, Depends(require(Perm.DEVICE_TEST))]

ADAPTER_TIMEOUT_S = 10


def _out(d: Device) -> DeviceOut:
    return DeviceOut(
        **{k: getattr(d, k) for k in DeviceOut.model_fields if k != "has_credentials"},
        has_credentials=bool(d.credentials_encrypted),
    )


def _adapter_cls(protocol: str) -> type[DeviceAdapter]:
    try:
        return get_adapter_class(protocol)
    except AdapterError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


def _clean_config(cls: type[DeviceAdapter], config: dict) -> dict:
    try:
        return cls.validate_config(config)
    except AdapterError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Connection settings: {e}") from None


def _clean_credentials(cls: type[DeviceAdapter], creds: dict[str, str]) -> dict[str, str]:
    unknown = set(creds) - cls.secret_keys()
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown credential field(s): {', '.join(sorted(unknown))}")
    return {k: v for k, v in creds.items() if v}


def _check_mappings(asset: Asset | None, mappings: list[PointMapping]) -> None:
    if not mappings:
        return
    if asset is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Point mappings need the device to be bound to an asset")
    known = {m["key"] for m in asset.asset_type.telemetry}
    bad = [m.measurement for m in mappings if m.measurement not in known]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Asset type '{asset.asset_type.name}' has no measurement(s): {', '.join(bad)}",
        )


def _check_controls(asset: Asset | None, mappings: list[ControlMapping], cls: type[DeviceAdapter]) -> None:
    if not mappings:
        return
    if asset is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Control mappings need the device to be bound to an asset")
    if not cls.supports_write:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{cls.name} devices can't execute commands")
    known = {c["key"] for c in asset.asset_type.controls}
    bad = [m.control for m in mappings if m.control not in known]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Asset type '{asset.asset_type.name}' has no control(s): {', '.join(bad)}")
    if cls.key == "modbus_tcp":
        from app.adapters.modbus_tcp import parse_point

        for m in mappings:
            try:
                p = parse_point(m.point)
            except AdapterError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
            if p.table in ("ir", "di"):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{m.point} is read-only; commands need co: or hr:")


def _check_points(cls: type[DeviceAdapter], mappings: list[PointMapping]) -> None:
    if cls.key == "modbus_tcp":
        from app.adapters.modbus_tcp import parse_point

        for m in mappings:
            try:
                parse_point(m.point)
            except AdapterError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


def _asset_in_factory(db, user: User, asset_id: str | None, factory_id: str) -> Asset | None:
    if asset_id is None:
        return None
    a = get_owned(db, Asset, asset_id, user, "Asset")
    if a.factory_id != factory_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Asset is in a different factory")
    return a


@router.get("/protocols", response_model=list[ProtocolOut])
def protocols(_: CurrentUser):
    return list_protocols()


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(user: CurrentUser, db: DB, factory_id: str | None = None, asset_id: str | None = None):
    q = select(Device).where(Device.org_id == user.org_id)
    if factory_id:
        q = q.where(Device.factory_id == factory_id)
    if asset_id:
        q = q.where(Device.asset_id == asset_id)
    return [_out(d) for d in db.scalars(q.order_by(Device.name)).all()]


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, user: CurrentUser, db: DB):
    return _out(get_owned(db, Device, device_id, user, "Device"))


@router.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(body: DeviceIn, user: Writer, db: DB):
    factory = get_owned(db, Factory, body.factory_id, user, "Factory")
    cls = _adapter_cls(body.protocol)
    asset = _asset_in_factory(db, user, body.asset_id, factory.id)
    _check_mappings(asset, body.point_mappings)
    _check_points(cls, body.point_mappings)
    _check_controls(asset, body.control_mappings, cls)
    creds = _clean_credentials(cls, body.credentials or {})
    d = Device(
        org_id=user.org_id,
        factory_id=factory.id,
        asset_id=body.asset_id,
        name=body.name,
        protocol=body.protocol,
        connection_config=_clean_config(cls, body.connection_config),
        credentials_encrypted=encrypt_json(creds) if creds else None,
        point_mappings=[m.model_dump() for m in body.point_mappings],
        control_mappings=[m.model_dump() for m in body.control_mappings],
        template_id=body.template_id,
        enabled=body.enabled,
    )
    db.add(d)
    db.flush()
    audit.record(db, user, "device.create", "device", d.id, f"Created {cls.name} device '{d.name}'")
    db.commit()
    return _out(d)


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(device_id: str, body: DevicePatch, user: Writer, db: DB):
    d = get_owned(db, Device, device_id, user, "Device")
    cls = _adapter_cls(d.protocol)
    changes = body.model_dump(exclude_unset=True)
    asset = d.asset_id and db.get(Asset, d.asset_id)
    if "asset_id" in changes:
        asset = _asset_in_factory(db, user, changes["asset_id"], d.factory_id)
    mappings = body.point_mappings if body.point_mappings is not None else [PointMapping(**m) for m in d.point_mappings]
    if "asset_id" in changes or "point_mappings" in changes:
        _check_mappings(asset or None, mappings)
        _check_points(cls, mappings)
    controls = body.control_mappings if body.control_mappings is not None else [ControlMapping(**m) for m in (d.control_mappings or [])]
    if "asset_id" in changes or "control_mappings" in changes:
        _check_controls(asset or None, controls, cls)
    summary_fields = sorted(changes)
    if "connection_config" in changes:
        changes["connection_config"] = _clean_config(cls, changes["connection_config"])
    if "credentials" in changes:
        creds = _clean_credentials(cls, changes.pop("credentials") or {})
        d.credentials_encrypted = encrypt_json(creds) if creds else None
    if "point_mappings" in changes:
        changes["point_mappings"] = [m.model_dump() for m in body.point_mappings]
    if "control_mappings" in changes:
        changes["control_mappings"] = [m.model_dump() for m in body.control_mappings]
    if {"connection_config", "credentials"} & set(summary_fields):
        d.last_test_status, d.last_test_message, d.last_test_at = "unknown", "Settings changed since last test", None
    for k, v in changes.items():
        setattr(d, k, v)
    # Never put secrets in the audit log; record which fields changed only.
    audit.record(db, user, "device.update", "device", d.id, f"Updated device '{d.name}'", {"fields": summary_fields})
    db.commit()
    return _out(d)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: str, user: Writer, db: DB):
    d = get_owned(db, Device, device_id, user, "Device")
    audit.record(db, user, "device.delete", "device", d.id, f"Deleted device '{d.name}'")
    db.delete(d)
    db.commit()
    return Response(status_code=204)


def _instance(d: Device) -> DeviceAdapter:
    cls = _adapter_cls(d.protocol)
    return cls(d.connection_config, decrypt_json(d.credentials_encrypted))


@router.get("/devices/{device_id}/diagnostics")
async def device_diagnostics(device_id: str, request: Request, user: CurrentUser, db: DB):
    d = get_owned(db, Device, device_id, user, "Device")
    rt = getattr(request.app.state, "telemetry", None)
    ctx = rt.devices.get(d.id) if rt else None
    if ctx is None:
        return {"active": False, "reason": "disabled" if not d.enabled else "not bound to an asset or not loaded yet"}
    st = await ctx.adapter.get_device_status()
    return {
        "active": True, "online": rt.device_online(ctx), "connected": st.connected, "protocol": ctx.protocol,
        "samples": ctx.samples, "errors": ctx.errors, "last_error": ctx.last_error or st.detail, "poll_ms": ctx.last_poll_ms,
        "last_seen": int(ctx.last_seen * 1000) if ctx.last_seen else None, "adapter": st.diagnostics,
    }


# ---------- device templates ----------
@router.get("/device-templates", response_model=list[TemplateOut])
def list_templates(user: CurrentUser, db: DB):
    return db.scalars(select(DeviceTemplate).where(DeviceTemplate.org_id == user.org_id).order_by(DeviceTemplate.protocol, DeviceTemplate.name)).all()


@router.post("/device-templates", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, user: Writer, db: DB):
    cls = _adapter_cls(body.protocol)
    if db.scalar(select(DeviceTemplate).where(DeviceTemplate.org_id == user.org_id, DeviceTemplate.key == body.key)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Template key '{body.key}' already exists")
    cfg = _clean_config(cls, body.connection_config)
    _check_points(cls, body.point_mappings)
    t = DeviceTemplate(org_id=user.org_id, **body.model_dump(mode="json", exclude={"connection_config"}), connection_config=cfg)
    db.add(t)
    db.flush()
    audit.record(db, user, "template.create", "device_template", t.id, f"Created device template {t.name}")
    db.commit()
    return t


@router.delete("/device-templates/{template_id}", status_code=204)
def delete_template(template_id: str, user: Writer, db: DB):
    t = get_owned(db, DeviceTemplate, template_id, user, "Template")
    if t.builtin:
        raise HTTPException(status.HTTP_409_CONFLICT, "Built-in templates can't be deleted")
    audit.record(db, user, "template.delete", "device_template", t.id, f"Deleted device template {t.name}")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


@router.post("/devices/{device_id}/test", response_model=TestResult)
async def test_device(device_id: str, user: Tester, db: DB):
    d = get_owned(db, Device, device_id, user, "Device")
    adapter = _instance(d)
    t0 = time.perf_counter()
    try:
        ok, msg = await asyncio.wait_for(adapter.test_connection(), ADAPTER_TIMEOUT_S)
    except TimeoutError:
        ok, msg = False, f"No response within {ADAPTER_TIMEOUT_S}s"
    except Exception as e:  # adapters talk to the outside world; report, don't crash
        ok, msg = False, f"{type(e).__name__}: {e}"
    latency = round((time.perf_counter() - t0) * 1000, 1)
    d.last_test_status = "ok" if ok else "error"
    d.last_test_message = msg[:1000]
    d.last_test_at = utcnow()
    audit.record(db, user, "device.test", "device", d.id, f"Connection test '{d.name}': {'OK' if ok else 'FAILED'}", {"message": msg})
    db.commit()
    return TestResult(ok=ok, message=msg, latency_ms=latency)


@router.post("/devices/{device_id}/discover", response_model=list[DiscoveredPoint])
async def discover_device(device_id: str, user: Tester, db: DB):
    d = get_owned(db, Device, device_id, user, "Device")
    adapter = _instance(d)
    if not adapter.supports_discovery:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{adapter.name} does not support discovery")
    try:
        return await asyncio.wait_for(adapter.discover_capabilities(), ADAPTER_TIMEOUT_S)
    except TimeoutError:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Discovery timed out") from None
