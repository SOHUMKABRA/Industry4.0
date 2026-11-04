from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, Timestamps
from app.schemas.definitions import KEY_PATTERN


class PointMapping(BaseModel):
    point: str = Field(min_length=1, max_length=200)  # protocol address / topic path
    measurement: str = Field(pattern=KEY_PATTERN)  # telemetry key on the asset type
    scale: float = 1.0
    offset: float = 0.0


class ControlMapping(BaseModel):
    control: str = Field(pattern=KEY_PATTERN)  # control key on the asset type
    point: str = Field(min_length=1, max_length=200)
    value: Any = None  # value written for commands (e.g. true, "running")
    param: str | None = None  # setpoints: which parameter supplies the value
    scale: float = 1.0  # raw = parameter × scale


class DeviceIn(BaseModel):
    factory_id: str
    name: str = Field(min_length=1, max_length=200)
    protocol: str
    asset_id: str | None = None
    connection_config: dict[str, Any] = Field(default_factory=dict)
    # Write-only. Stored encrypted; never returned.
    credentials: dict[str, str] | None = None
    point_mappings: list[PointMapping] = Field(default_factory=list)
    control_mappings: list[ControlMapping] = Field(default_factory=list)
    template_id: str | None = None
    enabled: bool = False


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    asset_id: str | None = None
    connection_config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None
    point_mappings: list[PointMapping] | None = None
    control_mappings: list[ControlMapping] | None = None
    enabled: bool | None = None


class DeviceOut(Timestamps):
    id: str
    factory_id: str
    asset_id: str | None
    name: str
    protocol: str
    connection_config: dict[str, Any]
    has_credentials: bool
    point_mappings: list[PointMapping]
    control_mappings: list[ControlMapping] = []
    template_id: str | None = None
    enabled: bool
    last_test_status: str
    last_test_message: str
    last_test_at: datetime | None


class ConfigField(BaseModel):
    key: str
    label: str
    type: str  # string | integer | number | boolean | enum
    required: bool = False
    default: Any = None
    options: list[str] = []
    secret: bool = False
    help: str = ""


class ProtocolOut(BaseModel):
    key: str
    name: str
    status: str  # available | planned
    description: str
    config_schema: list[ConfigField]
    supports_discovery: bool
    supports_write: bool


class TestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: float | None = None


class DiscoveredPoint(BaseModel):
    point: str
    label: str
    data_type: str
    unit: str = ""
    suggested_measurement: str | None = None


class AuditOut(ORMModel):
    id: str
    at: datetime
    user_email: str
    action: str
    entity_type: str
    entity_id: str | None
    summary: str
    details: dict


class TemplateIn(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    protocol: str
    description: str = Field(default="", max_length=2000)
    asset_type_key: str | None = None
    connection_config: dict[str, Any] = Field(default_factory=dict)
    point_mappings: list[PointMapping] = Field(default_factory=list)
    control_mappings: list[ControlMapping] = Field(default_factory=list)


class TemplateOut(ORMModel):
    id: str
    key: str
    name: str
    protocol: str
    description: str
    asset_type_key: str | None
    connection_config: dict[str, Any]
    point_mappings: list[PointMapping]
    control_mappings: list[ControlMapping]
    builtin: bool
