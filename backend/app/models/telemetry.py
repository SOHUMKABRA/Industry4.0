from datetime import datetime

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin, UTCDateTime


class TelemetryRecord(Base):
    """Historical telemetry. On PostgreSQL this becomes a Timescale hypertable."""

    __tablename__ = "telemetry_records"
    __table_args__ = (Index("ix_telemetry_asset_meas_ts", "asset_id", "measurement", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36))
    measurement: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(200))
    quality: Mapped[str] = mapped_column(String(10), default="good")
    source: Mapped[str] = mapped_column(String(10))  # live | simulated
    device_id: Mapped[str | None] = mapped_column(String(36))


class Dashboard(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "dashboards"

    factory_id: Mapped[str] = mapped_column(String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # [{id, type, title, size, asset_id?, measurement?, ...}] validated by schemas.dashboards
    widgets: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(320), default="")
