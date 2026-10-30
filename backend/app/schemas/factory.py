from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, Timestamps

AreaKind = Literal["production", "storage", "walkway", "safety", "utility", "office"]
LengthUnit = Literal["mm", "cm", "m", "ft"]


class FactoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    location: str = Field(default="", max_length=300)
    timezone: str = Field(default="UTC", max_length=64)
    length_unit: LengthUnit = "m"


class FactoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    timezone: str | None = Field(default=None, max_length=64)
    length_unit: LengthUnit | None = None


class FactoryOut(Timestamps):
    id: str
    name: str
    description: str
    location: str
    timezone: str
    length_unit: str


class Bounds(BaseModel):
    x: float = 0
    z: float = 0
    width: float = Field(default=10, gt=0)
    depth: float = Field(default=10, gt=0)


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: AreaKind = "production"
    bounds: Bounds = Field(default_factory=Bounds)


class AreaPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: AreaKind | None = None
    bounds: Bounds | None = None


class AreaOut(ORMModel):
    id: str
    floor_id: str
    name: str
    kind: str
    bounds: dict


class FloorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    level: int = 0
    elevation_m: float = 0
    width_m: float = Field(default=50, gt=0)
    depth_m: float = Field(default=30, gt=0)


class FloorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    level: int | None = None
    elevation_m: float | None = None
    width_m: float | None = Field(default=None, gt=0)
    depth_m: float | None = Field(default=None, gt=0)


class FloorOut(ORMModel):
    id: str
    factory_id: str
    name: str
    level: int
    elevation_m: float
    width_m: float
    depth_m: float
    areas: list[AreaOut] = []


class FactoryStructure(FactoryOut):
    floors: list[FloorOut]


class CountBy(BaseModel):
    key: str
    label: str
    count: int


class FactorySummary(BaseModel):
    factory_id: str
    asset_count: int
    device_count: int
    devices_enabled: int
    devices_untested: int
    devices_test_failed: int
    floors: int
    areas: int
    by_category: list[CountBy]
    by_area: list[CountBy]
    live_data_available: bool = False  # becomes true once Phase 4 ingestion runs
