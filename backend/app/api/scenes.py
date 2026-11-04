from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Asset, Factory, ModelFile, Scene, SceneObject, SceneVersion, User
from app.schemas.scenes import SceneObjectOut, SceneOut, SceneSave, SceneVersionOut, SceneWithObjects
from app.services import audit

router = APIRouter(tags=["scenes"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]

OBJ_FIELDS = [f for f in SceneObjectOut.model_fields]


def get_or_create_scene(db, user: User, factory_id: str) -> Scene:
    f = get_owned(db, Factory, factory_id, user, "Factory")
    scene = db.scalar(select(Scene).where(Scene.factory_id == f.id))
    if scene is None:
        scene = Scene(org_id=user.org_id, factory_id=f.id, name=f"{f.name} layout")
        db.add(scene)
        db.commit()
    return scene


def _objects(db, scene_id: str) -> list[SceneObject]:
    return list(db.scalars(select(SceneObject).where(SceneObject.scene_id == scene_id).order_by(SceneObject.sort, SceneObject.id)))


def _validate_refs(db, user: User, scene: Scene, objs: list[dict]) -> None:
    ids = [o["id"] for o in objs]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate object ids in scene")
    asset_ids = [o["asset_id"] for o in objs if o.get("asset_id")]
    if len(asset_ids) != len(set(asset_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An asset can be placed only once per layout")
    for o in objs:
        if o["kind"] == "asset" and not o.get("asset_id"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Object '{o['name']}' is an asset object without an asset")
        if o["kind"] != "asset" and o.get("asset_id"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Object '{o['name']}' ({o['kind']}) can't reference an asset")
    if asset_ids:
        ok = set(db.scalars(select(Asset.id).where(Asset.id.in_(asset_ids), Asset.org_id == user.org_id, Asset.factory_id == scene.factory_id)))
        missing = set(asset_ids) - ok
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{len(missing)} referenced asset(s) don't exist in this factory")
    model_ids = {o["model_id"] for o in objs if o.get("model_id")}
    if model_ids:
        ok = set(db.scalars(select(ModelFile.id).where(ModelFile.id.in_(model_ids), ModelFile.org_id == user.org_id)))
        if model_ids - ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown 3D model referenced")


def _write(db, user: User, scene: Scene, objs: list[dict], message: str) -> None:
    db.execute(delete(SceneObject).where(SceneObject.scene_id == scene.id))
    db.flush()
    db.add_all(SceneObject(org_id=user.org_id, scene_id=scene.id, **o) for o in objs)
    scene.version += 1
    scene.updated_by = user.email
    db.add(SceneVersion(
        org_id=user.org_id, scene_id=scene.id, version=scene.version, message=message,
        created_by=user.email, object_count=len(objs), snapshot=objs,
    ))


@router.get("/factories/{factory_id}/scene", response_model=SceneWithObjects)
def get_scene(factory_id: str, user: CurrentUser, db: DB):
    scene = get_or_create_scene(db, user, factory_id)
    return SceneWithObjects(scene=SceneOut.model_validate(scene), objects=[SceneObjectOut.model_validate(o) for o in _objects(db, scene.id)])


@router.put("/scenes/{scene_id}", response_model=SceneWithObjects)
def save_scene(scene_id: str, body: SceneSave, user: Writer, db: DB):
    scene = get_owned(db, Scene, scene_id, user, "Scene")
    if body.base_version != scene.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Layout was saved by {scene.updated_by or 'someone else'} (now v{scene.version}). Reload to get their changes.",
        )
    objs = [o.model_dump(mode="json") for o in body.objects]
    _validate_refs(db, user, scene, objs)
    _write(db, user, scene, objs, body.message)
    audit.record(db, user, "scene.save", "scene", scene.id, f"Saved layout v{scene.version} ({len(objs)} objects){': ' + body.message if body.message else ''}")
    db.commit()
    return get_scene(scene.factory_id, user, db)


@router.get("/scenes/{scene_id}/versions", response_model=list[SceneVersionOut])
def list_versions(scene_id: str, user: CurrentUser, db: DB):
    scene = get_owned(db, Scene, scene_id, user, "Scene")
    return db.scalars(select(SceneVersion).where(SceneVersion.scene_id == scene.id).order_by(SceneVersion.version.desc()).limit(200)).all()


@router.post("/scenes/{scene_id}/versions/{version}/restore", response_model=SceneWithObjects)
def restore_version(scene_id: str, version: int, user: Writer, db: DB):
    scene = get_owned(db, Scene, scene_id, user, "Scene")
    v = db.scalar(select(SceneVersion).where(SceneVersion.scene_id == scene.id, SceneVersion.version == version))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    objs = list(v.snapshot)
    # Assets deleted since that version can't be restored into the layout.
    asset_ids = [o["asset_id"] for o in objs if o.get("asset_id")]
    alive = set(db.scalars(select(Asset.id).where(Asset.id.in_(asset_ids)))) if asset_ids else set()
    kept = [o for o in objs if not o.get("asset_id") or o["asset_id"] in alive]
    dropped = len(objs) - len(kept)
    msg = f"Restored v{version}" + (f" ({dropped} object(s) for deleted assets skipped)" if dropped else "")
    _write(db, user, scene, kept, msg)
    audit.record(db, user, "scene.restore", "scene", scene.id, f"{msg} as v{scene.version}")
    db.commit()
    return get_scene(scene.factory_id, user, db)
