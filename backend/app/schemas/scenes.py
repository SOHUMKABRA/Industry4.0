from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

ObjectKind = Literal[
    "asset", "wall", "door", "window", "pillar", "zone", "walkway", "safety_zone",
    "workstation", "storage", "label", "box",
]
Vec3 = tuple[float, float, float]


class SceneObjectIn(BaseModel):
    id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    kind: ObjectKind
    asset_id: str | None = None
    name: str = Field(default="", max_length=200)
    shape: str = Field(default="box", max_length=32)
    position: Vec3 = (0, 0, 0)
    rotation: Vec3 = (0, 0, 0)
    scale: Vec3 = (1, 1, 1)
    size: Vec3 = (1, 1, 1)
    color: str = Field(default="#6b7a90", pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float = Field(default=1.0, ge=0.05, le=1.0)
    model_id: str | None = None
    floor_id: str | None = None
    group_id: str | None = Field(default=None, max_length=36)
    locked: bool = False
    hidden: bool = False
    sort: int = 0
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scale", "size")
    @classmethod
    def _positive(cls, v: Vec3):
        if any(x <= 0 or x > 10_000 for x in v):
            raise ValueError("must be > 0 and ≤ 10000")
        return v

    @field_validator("position")
    @classmethod
    def _bounded(cls, v: Vec3):
        if any(abs(x) > 100_000 for x in v):
            raise ValueError("position out of range (±100 km)")
        return v


class SceneObjectOut(SceneObjectIn, ORMModel):
    id: str


class SceneOut(ORMModel):
    id: str
    factory_id: str
    name: str
    version: int
    updated_by: str
    updated_at: datetime


class SceneWithObjects(BaseModel):
    scene: SceneOut
    objects: list[SceneObjectOut]


class SceneSave(BaseModel):
    base_version: int
    message: str = Field(default="", max_length=300)
    objects: list[SceneObjectIn] = Field(max_length=20_000)


class SceneVersionOut(ORMModel):
    id: str
    version: int
    message: str
    created_by: str
    created_at: datetime
    object_count: int


class ModelFileOut(ORMModel):
    id: str
    filename: str
    format: str
    size_bytes: int
    uploaded_by: str
    created_at: datetime


WidgetType = Literal["value", "gauge", "trend", "state", "kpis", "alarms", "devices"]


class Widget(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: WidgetType
    title: str = Field(default="", max_length=120)
    size: Literal["s", "m", "l", "w"] = "s"
    asset_id: str | None = None
    measurement: str | None = Field(default=None, max_length=64)
    minutes: int = Field(default=30, ge=1, le=1440)


class DashboardIn(BaseModel):
    factory_id: str
    name: str = Field(min_length=1, max_length=200)
    widgets: list[Widget] = Field(default_factory=list, max_length=100)


class DashboardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    widgets: list[Widget] | None = Field(default=None, max_length=100)


class DashboardOut(ORMModel):
    id: str
    factory_id: str
    name: str
    widgets: list[Widget]
    created_by: str
    updated_at: datetime
