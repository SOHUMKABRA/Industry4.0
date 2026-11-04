from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin, UTCDateTime, utcnow


class DeviceTemplate(IdMixin, TimestampMixin, OrgMixin, Base):
    """Reusable device configuration: protocol settings, point and control maps."""

    __tablename__ = "device_templates"

    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    protocol: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(2000), default="")
    asset_type_key: Mapped[str | None] = mapped_column(String(64), default=None)
    connection_config: Mapped[dict] = mapped_column(JSON, default=dict)
    point_mappings: Mapped[list] = mapped_column(JSON, default=list)
    control_mappings: Mapped[list] = mapped_column(JSON, default=list)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Interlock(IdMixin, TimestampMixin, OrgMixin, Base):
    """Permissive condition checked before a command is sent (fail closed).

    This is a supervisory check only. It never replaces PLC interlocks or
    hardwired safety circuits.
    """

    __tablename__ = "interlocks"

    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    control_key: Mapped[str] = mapped_column(String(64), default="*")  # '*' = every control on the asset
    source_asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id", ondelete="CASCADE"))
    measurement: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(4))  # == != < <= > >=
    value: Mapped[str] = mapped_column(String(200))  # compared numerically when both sides are numbers
    message: Mapped[str] = mapped_column(String(300), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ControlCommand(IdMixin, OrgMixin, Base):
    """One command through its lifecycle:
    REQUESTED → VALIDATING → [PENDING_APPROVAL] → APPROVED → SENT → ACKNOWLEDGED → COMPLETED
    or REJECTED / FAILED / TIMED_OUT / CANCELLED."""

    __tablename__ = "control_commands"
    __table_args__ = (Index("ix_cmd_asset_time", "asset_id", "requested_at"),)

    factory_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id", ondelete="CASCADE"))
    device_id: Mapped[str | None] = mapped_column(String(36))
    control_key: Mapped[str] = mapped_column(String(64))
    control_label: Mapped[str] = mapped_column(String(100), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), index=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[str] = mapped_column(String(320))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(320))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_message: Mapped[str] = mapped_column(Text, default="")
    checks: Mapped[list] = mapped_column(JSON, default=list)  # [{name, ok, detail}]
    events: Mapped[list] = mapped_column(JSON, default=list)  # [{status, at, detail}]


class Alert(IdMixin, OrgMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_factory_active", "factory_id", "active"),)

    factory_id: Mapped[str] = mapped_column(String(36))
    asset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    device_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16))  # limit | state | comm | command
    measurement: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(10))  # warning | alarm
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(String(500))
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(200))
    threshold: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(10), default="live")
    raised_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    cleared_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    acked: Mapped[bool] = mapped_column(Boolean, default=False)
    acked_by: Mapped[str | None] = mapped_column(String(320))
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
