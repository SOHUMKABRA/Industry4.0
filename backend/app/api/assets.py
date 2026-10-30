from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, AssetType, Factory, FactoryFloor, ProductionArea, User
from app.schemas.assets import AssetIn, AssetOut, AssetPatch
from app.services import audit
from app.services.properties import PropertyValidationError, validate_properties

router = APIRouter(prefix="/assets", tags=["assets"])
Writer = Annotated[User, Depends(require(Perm.ASSET_WRITE))]


def _check_area(db, user: User, area_id: str | None, factory_id: str) -> None:
    if area_id is None:
        return
    area = get_owned(db, ProductionArea, area_id, user, "Area")
    floor = db.get(FactoryFloor, area.floor_id)
    if floor.factory_id != factory_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Area belongs to a different factory")


def _check_parent(db, user: User, parent_id: str | None, factory_id: str, self_id: str | None = None) -> None:
    if parent_id is None:
        return
    parent = get_owned(db, Asset, parent_id, user, "Parent asset")
    if parent.factory_id != factory_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Parent asset is in a different factory")
    # Walk up the chain to reject cycles.
    seen = set()
    node = parent
    while node is not None:
        if node.id == self_id or node.id in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Parent would create a cycle")
        seen.add(node.id)
        node = db.get(Asset, node.parent_id) if node.parent_id else None


def _validated_props(t: AssetType, props: dict) -> dict:
    try:
        return validate_properties(t.property_schema, props)
    except PropertyValidationError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "Invalid properties", "fields": e.errors}
        ) from None


def _code_taken(db, user: User, code: str, exclude_id: str | None = None) -> bool:
    q = select(Asset.id).where(Asset.org_id == user.org_id, Asset.code == code)
    if exclude_id:
        q = q.where(Asset.id != exclude_id)
    return db.scalar(q) is not None


@router.get("", response_model=list[AssetOut])
def list_assets(
    user: CurrentUser,
    db: DB,
    factory_id: str | None = None,
    area_id: str | None = None,
    asset_type_id: str | None = None,
    category: str | None = None,
    parent_id: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=500, le=5000),
    offset: int = 0,
):
    stmt = select(Asset).where(Asset.org_id == user.org_id)
    if factory_id:
        stmt = stmt.where(Asset.factory_id == factory_id)
    if area_id:
        stmt = stmt.where(Asset.area_id == (None if area_id == "unassigned" else area_id))
    if asset_type_id:
        stmt = stmt.where(Asset.asset_type_id == asset_type_id)
    if parent_id:
        stmt = stmt.where(Asset.parent_id == parent_id)
    if category:
        stmt = stmt.join(AssetType, Asset.asset_type_id == AssetType.id).where(AssetType.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Asset.name.ilike(like), Asset.code.ilike(like), Asset.description.ilike(like)))
    return db.scalars(stmt.order_by(Asset.code).limit(limit).offset(offset)).unique().all()


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, user: CurrentUser, db: DB):
    return get_owned(db, Asset, asset_id, user, "Asset")


@router.post("", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, user: Writer, db: DB):
    factory = get_owned(db, Factory, body.factory_id, user, "Factory")
    t = get_owned(db, AssetType, body.asset_type_id, user, "Asset type")
    _check_area(db, user, body.area_id, factory.id)
    _check_parent(db, user, body.parent_id, factory.id)
    if _code_taken(db, user, body.code):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Asset ID '{body.code}' is already in use")
    data = body.model_dump()
    data["properties"] = _validated_props(t, body.properties)
    a = Asset(org_id=user.org_id, **data)
    db.add(a)
    db.flush()
    audit.record(db, user, "asset.create", "asset", a.id, f"Created {t.name} {a.code} '{a.name}'")
    db.commit()
    db.refresh(a)
    return a


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: str, body: AssetPatch, user: Writer, db: DB):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("version", None)
    if expected is not None and expected != a.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Asset was modified by someone else (now v{a.version}); reload and retry"
        )
    if "area_id" in changes:
        _check_area(db, user, changes["area_id"], a.factory_id)
    if "parent_id" in changes:
        _check_parent(db, user, changes["parent_id"], a.factory_id, self_id=a.id)
    if "code" in changes and _code_taken(db, user, changes["code"], exclude_id=a.id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Asset ID '{changes['code']}' is already in use")
    if "properties" in changes:
        changes["properties"] = _validated_props(a.asset_type, changes["properties"])
    before = {k: getattr(a, k) for k in changes}
    diff = audit.diff(before, changes)
    if not diff:
        return a
    for k, v in changes.items():
        setattr(a, k, v)
    a.version += 1
    audit.record(db, user, "asset.update", "asset", a.id, f"Updated {a.code} ({', '.join(sorted(diff))})", diff)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: str, user: Writer, db: DB):
    a = get_owned(db, Asset, asset_id, user, "Asset")
    audit.record(db, user, "asset.delete", "asset", a.id, f"Deleted {a.code} '{a.name}'",
                 {"snapshot": AssetOut.model_validate(a).model_dump(mode="json")})
    db.delete(a)
    db.commit()
    return Response(status_code=204)
