from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, AssetType, Device, Factory, FactoryFloor, ProductionArea, User
from app.schemas.factory import (
    AreaIn,
    AreaOut,
    AreaPatch,
    CountBy,
    FactoryIn,
    FactoryOut,
    FactoryPatch,
    FactoryStructure,
    FactorySummary,
    FloorIn,
    FloorOut,
    FloorPatch,
)
from app.services import audit

router = APIRouter(tags=["factories"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]


@router.get("/factories", response_model=list[FactoryOut])
def list_factories(user: CurrentUser, db: DB):
    return db.scalars(select(Factory).where(Factory.org_id == user.org_id).order_by(Factory.name)).all()


@router.post("/factories", response_model=FactoryOut, status_code=201)
def create_factory(body: FactoryIn, user: Writer, db: DB):
    f = Factory(org_id=user.org_id, **body.model_dump())
    db.add(f)
    db.flush()
    audit.record(db, user, "factory.create", "factory", f.id, f"Created factory {f.name}")
    db.commit()
    return f


@router.get("/factories/{factory_id}", response_model=FactoryStructure)
def get_factory(factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    f = db.scalar(
        select(Factory)
        .where(Factory.id == f.id)
        .options(selectinload(Factory.floors).selectinload(FactoryFloor.areas))
    )
    return f


@router.patch("/factories/{factory_id}", response_model=FactoryOut)
def update_factory(factory_id: str, body: FactoryPatch, user: Writer, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(f, k) for k in changes}
    for k, v in changes.items():
        setattr(f, k, v)
    audit.record(db, user, "factory.update", "factory", f.id, f"Updated factory {f.name}", audit.diff(before, changes))
    db.commit()
    return f


@router.delete("/factories/{factory_id}", status_code=204)
def delete_factory(factory_id: str, user: Annotated[User, Depends(require(Perm.USER_MANAGE))], db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    audit.record(db, user, "factory.delete", "factory", f.id, f"Deleted factory {f.name}")
    db.delete(f)
    db.commit()
    return Response(status_code=204)


@router.get("/factories/{factory_id}/summary", response_model=FactorySummary)
def factory_summary(factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    asset_count = db.scalar(select(func.count()).select_from(Asset).where(Asset.factory_id == f.id)) or 0
    dev_rows = db.execute(
        select(Device.enabled, Device.last_test_status, func.count())
        .where(Device.factory_id == f.id)
        .group_by(Device.enabled, Device.last_test_status)
    ).all()
    by_cat = db.execute(
        select(AssetType.category, func.count())
        .join(Asset, Asset.asset_type_id == AssetType.id)
        .where(Asset.factory_id == f.id)
        .group_by(AssetType.category)
        .order_by(func.count().desc())
    ).all()
    floors = db.scalars(select(FactoryFloor).where(FactoryFloor.factory_id == f.id)).all()
    floor_ids = [fl.id for fl in floors]
    areas = db.scalars(select(ProductionArea).where(ProductionArea.floor_id.in_(floor_ids))).all() if floor_ids else []
    area_counts = dict(
        db.execute(
            select(Asset.area_id, func.count()).where(Asset.factory_id == f.id).group_by(Asset.area_id)
        ).all()
    )
    by_area = [CountBy(key=a.id, label=a.name, count=area_counts.get(a.id, 0)) for a in areas]
    if area_counts.get(None):
        by_area.append(CountBy(key="unassigned", label="Unassigned", count=area_counts[None]))
    return FactorySummary(
        factory_id=f.id,
        asset_count=asset_count,
        device_count=sum(r[2] for r in dev_rows),
        devices_enabled=sum(r[2] for r in dev_rows if r[0]),
        devices_untested=sum(r[2] for r in dev_rows if r[1] == "unknown"),
        devices_test_failed=sum(r[2] for r in dev_rows if r[1] == "error"),
        floors=len(floors),
        areas=len(areas),
        by_category=[CountBy(key=c, label=c.replace("_", " ").title(), count=n) for c, n in by_cat],
        by_area=by_area,
    )


# ---- floors ----
@router.post("/factories/{factory_id}/floors", response_model=FloorOut, status_code=201)
def create_floor(factory_id: str, body: FloorIn, user: Writer, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    fl = FactoryFloor(org_id=user.org_id, factory_id=f.id, **body.model_dump())
    db.add(fl)
    db.flush()
    audit.record(db, user, "floor.create", "floor", fl.id, f"Added floor {fl.name} to {f.name}")
    db.commit()
    db.refresh(fl)
    return fl


@router.patch("/floors/{floor_id}", response_model=FloorOut)
def update_floor(floor_id: str, body: FloorPatch, user: Writer, db: DB):
    fl = get_owned(db, FactoryFloor, floor_id, user, "Floor")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(fl, k) for k in changes}
    for k, v in changes.items():
        setattr(fl, k, v)
    audit.record(db, user, "floor.update", "floor", fl.id, f"Updated floor {fl.name}", audit.diff(before, changes))
    db.commit()
    return fl


@router.delete("/floors/{floor_id}", status_code=204)
def delete_floor(floor_id: str, user: Writer, db: DB):
    fl = get_owned(db, FactoryFloor, floor_id, user, "Floor")
    audit.record(db, user, "floor.delete", "floor", fl.id, f"Deleted floor {fl.name}")
    db.delete(fl)
    db.commit()
    return Response(status_code=204)


# ---- areas ----
@router.post("/floors/{floor_id}/areas", response_model=AreaOut, status_code=201)
def create_area(floor_id: str, body: AreaIn, user: Writer, db: DB):
    fl = get_owned(db, FactoryFloor, floor_id, user, "Floor")
    a = ProductionArea(org_id=user.org_id, floor_id=fl.id, name=body.name, kind=body.kind, bounds=body.bounds.model_dump())
    db.add(a)
    db.flush()
    audit.record(db, user, "area.create", "area", a.id, f"Added area {a.name} to {fl.name}")
    db.commit()
    return a


@router.patch("/areas/{area_id}", response_model=AreaOut)
def update_area(area_id: str, body: AreaPatch, user: Writer, db: DB):
    a = get_owned(db, ProductionArea, area_id, user, "Area")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(a, k) for k in changes}
    for k, v in changes.items():
        setattr(a, k, v)
    audit.record(db, user, "area.update", "area", a.id, f"Updated area {a.name}", audit.diff(before, changes))
    db.commit()
    return a


@router.delete("/areas/{area_id}", status_code=204)
def delete_area(area_id: str, user: Writer, db: DB):
    a = get_owned(db, ProductionArea, area_id, user, "Area")
    in_use = db.scalar(select(func.count()).select_from(Asset).where(Asset.area_id == a.id))
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Area still contains {in_use} asset(s); move them first")
    audit.record(db, user, "area.delete", "area", a.id, f"Deleted area {a.name}")
    db.delete(a)
    db.commit()
    return Response(status_code=204)
