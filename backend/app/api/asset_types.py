from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, AssetType, User
from app.schemas.assets import AssetTypeIn, AssetTypeOut, AssetTypePatch
from app.services import audit
from app.services.properties import PropertyValidationError, validate_properties

router = APIRouter(prefix="/asset-types", tags=["asset types"])
Writer = Annotated[User, Depends(require(Perm.ASSET_TYPE_WRITE))]


def _out(t: AssetType, count: int = 0) -> AssetTypeOut:
    o = AssetTypeOut.model_validate(t)
    o.asset_count = count
    return o


@router.get("", response_model=list[AssetTypeOut])
def list_asset_types(user: CurrentUser, db: DB, category: str | None = None):
    q = select(AssetType).where(AssetType.org_id == user.org_id)
    if category:
        q = q.where(AssetType.category == category)
    types = db.scalars(q.order_by(AssetType.category, AssetType.name)).all()
    counts = dict(
        db.execute(
            select(Asset.asset_type_id, func.count()).where(Asset.org_id == user.org_id).group_by(Asset.asset_type_id)
        ).all()
    )
    return [_out(t, counts.get(t.id, 0)) for t in types]


@router.get("/{type_id}", response_model=AssetTypeOut)
def get_asset_type(type_id: str, user: CurrentUser, db: DB):
    t = get_owned(db, AssetType, type_id, user, "Asset type")
    n = db.scalar(select(func.count()).select_from(Asset).where(Asset.asset_type_id == t.id)) or 0
    return _out(t, n)


@router.post("", response_model=AssetTypeOut, status_code=201)
def create_asset_type(body: AssetTypeIn, user: Writer, db: DB):
    if db.scalar(select(AssetType).where(AssetType.org_id == user.org_id, AssetType.key == body.key)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Asset type key '{body.key}' already exists")
    t = AssetType(org_id=user.org_id, **body.model_dump(mode="json"))
    db.add(t)
    db.flush()
    audit.record(db, user, "asset_type.create", "asset_type", t.id, f"Created asset type {t.name}")
    db.commit()
    return _out(t)


@router.patch("/{type_id}", response_model=AssetTypeOut)
def update_asset_type(type_id: str, body: AssetTypePatch, user: Writer, db: DB):
    t = get_owned(db, AssetType, type_id, user, "Asset type")
    changes = body.model_dump(mode="json", exclude_unset=True)
    assets = db.scalars(select(Asset).where(Asset.asset_type_id == t.id)).all()

    if "property_schema" in changes:
        # Existing assets must remain valid under the new schema. Values for
        # removed properties are dropped (the user removed the definition);
        # anything else that fails blocks the change.
        new_keys = {p["key"] for p in changes["property_schema"]}
        cleaned: dict[str, dict] = {}
        failures: list[str] = []
        for a in assets:
            kept = {k: v for k, v in (a.properties or {}).items() if k in new_keys}
            try:
                cleaned[a.id] = validate_properties(changes["property_schema"], kept)
            except PropertyValidationError as e:
                failures.append(f"{a.code}: {e}")
        if failures:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Change would make existing assets invalid", "assets": failures[:10]},
            )
        for a in assets:
            if a.properties != cleaned[a.id]:
                a.properties = cleaned[a.id]
                a.version += 1

    before = {k: getattr(t, k) for k in changes}
    for k, v in changes.items():
        setattr(t, k, v)
    t.version += 1
    audit.record(
        db, user, "asset_type.update", "asset_type", t.id, f"Updated asset type {t.name} (v{t.version})",
        {"fields": sorted(changes), "before": before},
    )
    db.commit()
    return _out(t, len(assets))


@router.delete("/{type_id}", status_code=204)
def delete_asset_type(type_id: str, user: Writer, db: DB):
    t = get_owned(db, AssetType, type_id, user, "Asset type")
    n = db.scalar(select(func.count()).select_from(Asset).where(Asset.asset_type_id == t.id))
    if n:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{n} asset(s) use this type")
    audit.record(db, user, "asset_type.delete", "asset_type", t.id, f"Deleted asset type {t.name}")
    db.delete(t)
    db.commit()
    return Response(status_code=204)
