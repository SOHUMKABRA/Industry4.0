"""Typed definitions stored in AssetType JSON columns.

These are the contract that lets users add machine/sensor kinds without code
changes while still validating everything that goes into the database.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class _Def(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyDef(_Def):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    type: Literal["number", "integer", "string", "boolean", "enum"]
    unit: str = ""
    required: bool = False
    min: float | None = None
    max: float | None = None
    options: list[str] = Field(default_factory=list)
    default: Any = None
    group: str = "General"
    help: str = ""

    @model_validator(mode="after")
    def _check(self):
        if self.type == "enum" and not self.options:
            raise ValueError(f"property '{self.key}': enum needs options")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"property '{self.key}': min > max")
        return self


class TelemetryDef(_Def):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    data_type: Literal["number", "integer", "boolean", "string", "enum"] = "number"
    unit: str = ""
    min: float | None = None
    max: float | None = None
    warn_low: float | None = None
    warn_high: float | None = None
    alarm_low: float | None = None
    alarm_high: float | None = None
    options: list[str] = Field(default_factory=list)
    # Expected max interval between samples; used for stale detection (Phase 4).
    expected_interval_s: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.data_type == "enum" and not self.options:
            raise ValueError(f"telemetry '{self.key}': enum needs options")
        return self


class ControlParam(_Def):
    key: str = Field(pattern=KEY_PATTERN)
    label: str
    type: Literal["number", "integer", "boolean", "enum"] = "number"
    unit: str = ""
    min: float | None = None
    max: float | None = None
    options: list[str] = Field(default_factory=list)


class ControlDef(_Def):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["command", "setpoint"] = "command"
    params: list[ControlParam] = Field(default_factory=list)
    requires_confirmation: bool = True
    min_role: Literal["operator", "engineer", "admin"] = "operator"
    # Telemetry key whose value confirms the command took effect (Phase 5).
    feedback_measurement: str | None = None
    description: str = ""


class VisualDef(_Def):
    shape: Literal["box", "cylinder", "sphere", "conveyor", "robot_arm", "tank", "panel", "sensor", "line"] = "box"
    color: str = Field(default="#6b7a90", pattern=r"^#[0-9a-fA-F]{6}$")
    model_url: str | None = None
    # Default footprint in metres [width, height, depth]
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)


def unique_keys(items: list[_Def], what: str) -> None:
    seen: set[str] = set()
    for it in items:
        k = it.key  # type: ignore[attr-defined]
        if k in seen:
            raise ValueError(f"duplicate {what} key '{k}'")
        seen.add(k)
