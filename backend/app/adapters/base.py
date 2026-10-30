"""Device adapter contract.

Every protocol integration implements DeviceAdapter. The platform core only
talks to this interface; adding a protocol means adding an adapter module and
registering it — no changes elsewhere. See DEVICE_INTEGRATION.md.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from app.schemas.devices import ConfigField, DiscoveredPoint

Quality = Literal["good", "uncertain", "bad"]


@dataclass(frozen=True)
class Sample:
    point: str
    value: Any
    ts: datetime
    quality: Quality = "good"
    seq: int | None = None


@dataclass
class CommandAck:
    accepted: bool
    message: str = ""
    # Acknowledgement means the device/controller accepted the request. It is
    # NOT proof the physical action happened; the command engine verifies that
    # separately through telemetry (Phase 5).


@dataclass
class DeviceStatus:
    connected: bool
    detail: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class AdapterError(Exception):
    pass


class DeviceAdapter(abc.ABC):
    # --- static description, used by the UI to render config forms ---
    key: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    config_schema: ClassVar[list[ConfigField]] = []
    supports_discovery: ClassVar[bool] = False
    supports_write: ClassVar[bool] = False

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None):
        self.config = config
        self.credentials = credentials or {}

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Validate non-secret config against config_schema; return cleaned copy."""
        out: dict[str, Any] = {}
        errors: list[str] = []
        fields = {f.key: f for f in cls.config_schema if not f.secret}
        for k in config:
            if k not in fields:
                errors.append(f"unknown setting '{k}'")
        for f in fields.values():
            v = config.get(f.key, f.default)
            if v is None or v == "":
                if f.required:
                    errors.append(f"'{f.label}' is required")
                continue
            try:
                if f.type == "integer":
                    if isinstance(v, bool) or int(v) != float(v):
                        raise ValueError
                    v = int(v)
                elif f.type == "number":
                    if isinstance(v, bool):
                        raise ValueError
                    v = float(v)
                elif f.type == "boolean":
                    if not isinstance(v, bool):
                        raise ValueError
                elif f.type == "enum":
                    if v not in f.options:
                        raise ValueError
                else:
                    v = str(v)
            except (TypeError, ValueError):
                errors.append(f"'{f.label}' has an invalid value")
                continue
            out[f.key] = v
        if errors:
            raise AdapterError("; ".join(errors))
        return out

    @classmethod
    def secret_keys(cls) -> set[str]:
        return {f.key for f in cls.config_schema if f.secret}

    # --- lifecycle ---
    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @abc.abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """Open, probe, and close. Must not change device state."""

    async def discover_capabilities(self) -> list[DiscoveredPoint]:
        return []

    @abc.abstractmethod
    async def read_telemetry(self, points: list[str]) -> list[Sample]: ...

    async def write_command(self, point: str, value: Any) -> CommandAck:
        raise AdapterError(f"{self.name} adapter does not support writes")

    @abc.abstractmethod
    async def get_device_status(self) -> DeviceStatus: ...

    async def get_diagnostics(self) -> dict[str, Any]:
        return (await self.get_device_status()).diagnostics
