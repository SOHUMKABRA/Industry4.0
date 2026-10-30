from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, Timestamps
from app.schemas.definitions import (
    KEY_PATTERN,
    ControlDef,
    PropertyDef,
    TelemetryDef,
    VisualDef,
    unique_keys,
)

Lifecycle = Literal["active", "maintenance", "decommissioned"]


class AssetTypeIn(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="box", max_length=32)
    property_schema: list[PropertyDef] = Field(default_factory=list)
    telemetry: list[TelemetryDef] = Field(default_factory=list)
    controls: list[ControlDef] = Field(default_factory=list)
    visual: VisualDef = Field(default_factory=VisualDef)

    @field_validator("property_schema", "telemetry", "controls")
    @classmethod
    def _unique(cls, v, info):
        unique_keys(v, info.field_name)
        return v


class AssetTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=32)
    property_schema: list[PropertyDef] | None = None
    telemetry: list[TelemetryDef] | None = None
    controls: list[ControlDef] | None = None
    visual: VisualDef | None = None

    @field_validator("property_schema", "telemetry", "controls")
    @classmethod
    def _unique(cls, v, info):
        if v is not None:
            unique_keys(v, info.field_name)
        return v


class AssetTypeOut(Timestamps):
    id: str
    key: str
    name: str
    category: str
    description: str
    icon: str
    property_schema: list[PropertyDef]
    telemetry: list[TelemetryDef]
    controls: list[ControlDef]
    visual: VisualDef
    version: int
    asset_count: int = 0


class AssetIn(BaseModel):
    factory_id: str
    asset_type_id: str
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
    name: str = Field(min_length=1, max_length=200)
    area_id: str | None = None
    parent_id: str | None = None
    description: str = Field(default="", max_length=2000)
    manufacturer: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    serial_number: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=50)
    properties: dict[str, Any] = Field(default_factory=dict)
    lifecycle_status: Lifecycle = "active"


class AssetPatch(BaseModel):
    """Partial update. `version` enables optimistic concurrency (409 on mismatch)."""

    version: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    area_id: str | None = None
    parent_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = Field(default=None, max_length=50)
    properties: dict[str, Any] | None = None
    lifecycle_status: Lifecycle | None = None


class AssetTypeBrief(ORMModel):
    id: str
    key: str
    name: str
    category: str
    icon: str


class AssetOut(Timestamps):
    id: str
    factory_id: str
    area_id: str | None
    parent_id: str | None
    asset_type_id: str
    asset_type: AssetTypeBrief
    code: str
    name: str
    description: str
    manufacturer: str
    model: str
    serial_number: str
    tags: list[str]
    properties: dict[str, Any]
    lifecycle_status: str
    version: int
