from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin


class AssetType(IdMixin, TimestampMixin, OrgMixin, Base):
    """Data-defined kind of asset. Adding a machine/sensor kind = adding a row."""

    __tablename__ = "asset_types"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_asset_type_key"),)

    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(String(2000), default="")
    icon: Mapped[str] = mapped_column(String(32), default="box")
    # Validated lists; see app.schemas.definitions.
    property_schema: Mapped[list] = mapped_column(JSON, default=list)
    telemetry: Mapped[list] = mapped_column(JSON, default=list)
    controls: Mapped[list] = mapped_column(JSON, default=list)
    visual: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Asset(IdMixin, TimestampMixin, OrgMixin, Base):
    """Physical asset identity. Deliberately has no geometry: visual
    representations (scene objects, 2D symbols, widgets) reference it."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_asset_code"),)

    factory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True
    )
    area_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("production_areas.id", ondelete="SET NULL"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    asset_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_types.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))  # human asset ID, e.g. "MTR-101"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    serial_number: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    # Per-asset overrides of telemetry limits: {measurement_key: {warn_high: ...}}
    operating_limits: Mapped[dict] = mapped_column(JSON, default=dict)
    # Lifecycle, not live state: active | maintenance | decommissioned
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)

    asset_type: Mapped[AssetType] = relationship(lazy="joined")
