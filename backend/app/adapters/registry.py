"""Protocol adapter registry.

Available adapters are classes implementing DeviceAdapter. Planned protocols are
listed so the roadmap is visible, but they cannot be selected for a device until
an adapter exists — the platform never pretends to support a protocol.
"""

from app.adapters.base import AdapterError, DeviceAdapter
from app.adapters.simulated import SimulatedAdapter
from app.schemas.devices import ProtocolOut

_ADAPTERS: dict[str, type[DeviceAdapter]] = {}

PLANNED: dict[str, tuple[str, str]] = {
    "mqtt": ("MQTT", "Phase 3. Subscribe to broker topics, JSON or raw payloads."),
    "modbus_tcp": ("Modbus TCP", "Phase 3. Poll holding/input registers and coils."),
    "opcua": ("OPC UA", "Planned. Browse nodes, subscriptions."),
    "http": ("HTTP REST (poll)", "Planned."),
    "webhook": ("Webhook (push)", "Planned."),
    "modbus_rtu": ("Modbus RTU / RS485", "Planned. Requires serial hardware on an edge gateway."),
    "s7": ("Siemens S7", "Planned. Requires snap7 on an edge gateway."),
    "ethernet_ip": ("EtherNet/IP", "Planned."),
    "bacnet": ("BACnet/IP", "Planned."),
}


def register(cls: type[DeviceAdapter]) -> type[DeviceAdapter]:
    _ADAPTERS[cls.key] = cls
    return cls


register(SimulatedAdapter)


def get_adapter_class(key: str) -> type[DeviceAdapter]:
    try:
        return _ADAPTERS[key]
    except KeyError:
        if key in PLANNED:
            raise AdapterError(f"Protocol '{PLANNED[key][0]}' is not implemented yet") from None
        raise AdapterError(f"Unknown protocol '{key}'") from None


def list_protocols() -> list[ProtocolOut]:
    out = [
        ProtocolOut(
            key=c.key,
            name=c.name,
            status="available",
            description=c.description,
            config_schema=c.config_schema,
            supports_discovery=c.supports_discovery,
            supports_write=c.supports_write,
        )
        for c in _ADAPTERS.values()
    ]
    out += [
        ProtocolOut(
            key=k, name=n, status="planned", description=d, config_schema=[],
            supports_discovery=False, supports_write=False,
        )
        for k, (n, d) in PLANNED.items()
        if k not in _ADAPTERS
    ]
    return out
