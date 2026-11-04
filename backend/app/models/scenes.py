from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin


class Scene(IdMixin, TimestampMixin, OrgMixin, Base):
    """The spatial layout of a factory. One scene per factory; 2D and 3D views
    both render the same scene objects."""

    __tablename__ = "scenes"

    factory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("factories.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="Main layout")
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[str] = mapped_column(String(320), default="")


class SceneObject(OrgMixin, Base):
    """A visual representation placed in a scene.

    kind='asset' objects reference an Asset (the physical identity); building
    elements (walls, zones, ...) exist only in the scene. Deleting an asset
    removes its scene objects; deleting a scene object never deletes the asset.
    """

    __tablename__ = "scene_objects"

    # Client-generated UUIDs so the editor can create objects offline/undoably.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200), default="")
    shape: Mapped[str] = mapped_column(String(32), default="box")
    position: Mapped[list] = mapped_column(JSON, default=lambda: [0, 0, 0])
    rotation: Mapped[list] = mapped_column(JSON, default=lambda: [0, 0, 0])
    scale: Mapped[list] = mapped_column(JSON, default=lambda: [1, 1, 1])
    size: Mapped[list] = mapped_column(JSON, default=lambda: [1, 1, 1])
    color: Mapped[str] = mapped_column(String(9), default="#6b7a90")
    opacity: Mapped[float] = mapped_column(Float, default=1.0)
    model_id: Mapped[str | None] = mapped_column(String(36), default=None)
    floor_id: Mapped[str | None] = mapped_column(String(36), default=None)
    group_id: Mapped[str | None] = mapped_column(String(36), default=None)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    props: Mapped[dict] = mapped_column(JSON, default=dict)


class SceneVersion(IdMixin, TimestampMixin, OrgMixin, Base):
    """Immutable snapshot written on every save; restoring creates a new version."""

    __tablename__ = "scene_versions"

    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenes.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(320), default="")
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[list] = mapped_column(JSON, default=list)


class ModelFile(IdMixin, TimestampMixin, OrgMixin, Base):
    """Uploaded 3D model (GLB/OBJ/STL). Bytes live on disk/object storage."""

    __tablename__ = "model_files"

    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[str] = mapped_column(String(320), default="")
