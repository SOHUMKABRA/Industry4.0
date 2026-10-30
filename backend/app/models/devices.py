from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin, UTCDateTime


class Device(IdMixin, TimestampMixin, OrgMixin, Base):
    """A data source / control endpoint, bound to an asset via adapters."""

    __tablename__ = "devices"

    factory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(String(32))
    # Non-secret connection settings, validated by the adapter's config_schema.
    connection_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Fernet-encrypted JSON of secret fields. Never returned by the API.
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    # Data-point → asset measurement mappings: [{point, measurement, scale, offset}]
    point_mappings: Mapped[list] = mapped_column(JSON, default=list)
    gateway_id: Mapped[str | None] = mapped_column(String(36), default=None)
    enabled: Mapped[bool] = mapped_column(default=False)
    # unknown | ok | error  (result of the last connection test, not live status)
    last_test_status: Mapped[str] = mapped_column(String(16), default="unknown")
    last_test_message: Mapped[str] = mapped_column(String(1000), default="")
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
