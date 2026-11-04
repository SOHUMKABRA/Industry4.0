"""3D model uploads (GLB, OBJ, STL). FBX must be converted to GLB first."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import ModelFile, SceneObject, User
from app.models.base import new_id
from app.schemas.scenes import ModelFileOut
from app.services import audit

router = APIRouter(prefix="/models", tags=["3d models"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]

MEDIA = {"glb": "model/gltf-binary", "obj": "text/plain", "stl": "model/stl"}


def _sniff(fmt: str, head: bytes) -> bool:
    if fmt == "glb":
        return head[:4] == b"glTF"
    if fmt == "stl":
        return True  # binary STL has no magic; ASCII starts with 'solid'. Parsed client-side.
    if fmt == "obj":
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


@router.get("", response_model=list[ModelFileOut])
def list_models(user: CurrentUser, db: DB):
    return db.scalars(select(ModelFile).where(ModelFile.org_id == user.org_id).order_by(ModelFile.created_at.desc())).all()


@router.post("", response_model=ModelFileOut, status_code=201)
async def upload_model(file: UploadFile, user: Writer, db: DB):
    s = get_settings()
    name = Path(file.filename or "model").name
    fmt = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if fmt == "fbx":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "FBX isn't supported directly: convert it to GLB (e.g. Blender → Export glTF Binary)")
    if fmt not in MEDIA:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Supported formats: .glb, .obj, .stl")
    limit = s.max_model_mb * 1024 * 1024
    mid = new_id()
    folder = Path(s.model_storage_dir) / user.org_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{mid}.{fmt}"
    size = 0
    head = b""
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                if not head:
                    head = chunk[:64]
                    if not _sniff(fmt, head):
                        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"File content doesn't look like a valid .{fmt}")
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Model larger than {s.max_model_mb} MB")
                out.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Empty file")
    m = ModelFile(id=mid, org_id=user.org_id, filename=name[:255], format=fmt, size_bytes=size, storage_path=str(path), uploaded_by=user.email)
    db.add(m)
    audit.record(db, user, "model.upload", "model", m.id, f"Uploaded 3D model {name} ({size // 1024} KB)")
    db.commit()
    return m


@router.get("/{model_id}/file")
def model_file(model_id: str, user: CurrentUser, db: DB):
    m = get_owned(db, ModelFile, model_id, user, "Model")
    if not os.path.exists(m.storage_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model file missing from storage")
    return FileResponse(m.storage_path, media_type=MEDIA[m.format], headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str, user: Writer, db: DB):
    m = get_owned(db, ModelFile, model_id, user, "Model")
    used = db.scalar(select(SceneObject.id).where(SceneObject.model_id == m.id).limit(1))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "Model is used in a layout; remove it from objects first")
    Path(m.storage_path).unlink(missing_ok=True)
    audit.record(db, user, "model.delete", "model", m.id, f"Deleted 3D model {m.filename}")
    db.delete(m)
    db.commit()
    return Response(status_code=204)
