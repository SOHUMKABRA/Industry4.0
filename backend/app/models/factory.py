from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin


class Factory(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "factories"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # Display unit for lengths; storage is always metres.
    length_unit: Mapped[str] = mapped_column(String(4), default="m")

    floors: Mapped[list["FactoryFloor"]] = relationship(
        back_populates="factory", cascade="all, delete-orphan", order_by="FactoryFloor.level"
    )


class FactoryFloor(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "factory_floors"

    factory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer, default=0)
    elevation_m: Mapped[float] = mapped_column(Float, default=0.0)
    width_m: Mapped[float] = mapped_column(Float, default=50.0)
    depth_m: Mapped[float] = mapped_column(Float, default=30.0)

    factory: Mapped[Factory] = relationship(back_populates="floors")
    areas: Mapped[list["ProductionArea"]] = relationship(
        back_populates="floor", cascade="all, delete-orphan", order_by="ProductionArea.name"
    )


class ProductionArea(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "production_areas"

    floor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("factory_floors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # production | storage | walkway | safety | utility | office
    kind: Mapped[str] = mapped_column(String(32), default="production")
    # Footprint rectangle on the floor, metres: {x, z, width, depth}
    bounds: Mapped[dict] = mapped_column(JSON, default=dict)

    floor: Mapped[FactoryFloor] = relationship(back_populates="areas")
