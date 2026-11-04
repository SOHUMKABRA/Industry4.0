from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, OrgMixin, TimestampMixin, UTCDateTime, utcnow


class TelemetryHourly(Base):
    """Hourly roll-up of telemetry, kept long after raw data is pruned.

    Numbers: avg/min/max/first/last/count. State-like text measurements: seconds
    spent in each state plus the number of transitions into "running" (`_starts`).
    """

    __tablename__ = "telemetry_hourly"
    __table_args__ = (UniqueConstraint("asset_id", "measurement", "hour", name="uq_rollup"),
                      Index("ix_rollup_org_hour", "org_id", "hour"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(36))
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    measurement: Mapped[str] = mapped_column(String(64))
    hour: Mapped[datetime] = mapped_column(UTCDateTime())
    count: Mapped[int] = mapped_column(Integer, default=0)
    avg: Mapped[float | None] = mapped_column(Float)
    min: Mapped[float | None] = mapped_column(Float)
    max: Mapped[float | None] = mapped_column(Float)
    first_num: Mapped[float | None] = mapped_column(Float)
    last_num: Mapped[float | None] = mapped_column(Float)
    last_text: Mapped[str | None] = mapped_column(String(200))
    states: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(10), default="live")


class NotificationChannel(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "notification_channels"

    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16))  # webhook | email
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret settings
    secrets_encrypted: Mapped[str | None] = mapped_column(Text)  # webhook HMAC secret / SMTP password
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alerts: Mapped[bool] = mapped_column(Boolean, default=True)  # receive alert events
    min_severity: Mapped[str] = mapped_column(String(10), default="warning")
    notify_clear: Mapped[bool] = mapped_column(Boolean, default=False)


class NotificationDelivery(IdMixin, OrgMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_delivery_channel_at", "channel_id", "at"),)

    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("notification_channels.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    event: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10))  # sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    detail: Mapped[str] = mapped_column(String(500), default="")


class AutomationRule(IdMixin, TimestampMixin, OrgMixin, Base):
    __tablename__ = "automation_rules"

    factory_id: Mapped[str] = mapped_column(String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger: Mapped[dict] = mapped_column(JSON, default=dict)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=60)
    run_as_user_id: Mapped[str] = mapped_column(String(36))  # whose permissions commands use
    created_by: Mapped[str] = mapped_column(String(320), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AutomationExecution(IdMixin, OrgMixin, Base):
    __tablename__ = "automation_executions"
    __table_args__ = (Index("ix_autoexec_rule_at", "rule_id", "started_at"),)

    rule_id: Mapped[str] = mapped_column(String(36), ForeignKey("automation_rules.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(12))  # running | succeeded | partial | failed | dry_run
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger_detail: Mapped[str] = mapped_column(String(500), default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)


class SimulationScenario(IdMixin, TimestampMixin, OrgMixin, Base):
    """Scripted fault injection for simulated devices only (never field devices)."""

    __tablename__ = "simulation_scenarios"

    factory_id: Mapped[str] = mapped_column(String(36), ForeignKey("factories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default="")
    # [{at_s, device_id, action: "set"|"offline"|"restore", point?, value?, duration_s?}]
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(320), default="")
