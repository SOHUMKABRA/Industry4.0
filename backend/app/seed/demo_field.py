"""Demo field integration (Phase 3/5): real-protocol devices against the lab field simulator.

The lab simulator (tools/field_sim) is a separate process that behaves like plant
equipment: a Modbus TCP PLC for Line 3 (with its own run logic and E-stop) and
MQTT field transmitters. From the platform's point of view these are ordinary
Modbus/MQTT devices, exactly like the customer's machinery will be.

Idempotent; only touches the demo organization, and only disables simulated
devices that still have their seeded configuration.
"""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, AssetType, Device, DeviceTemplate, Factory, Interlock, Organization
from app.seed.demo import DEMO_SLUG
from app.services import audit

LAB_HOST = os.environ.get("LAB_HOST", "127.0.0.1")
MODBUS_PORT = int(os.environ.get("LAB_MODBUS_PORT", "5020"))
MQTT_PORT = int(os.environ.get("LAB_MQTT_PORT", "1883"))

STATE_MAP = "map=0=stopped;1=running;2=fault;3=maintenance;4=emergency_stop"


def _pm(point, measurement, scale=1.0, offset=0.0):
    return {"point": point, "measurement": measurement, "scale": scale, "offset": offset}


def _cm(control, point, value=None, param=None, scale=1.0):
    return {"control": control, "point": point, "value": value, "param": param, "scale": scale}


MODBUS_CFG = {"host": LAB_HOST, "port": MODBUS_PORT, "unit_id": 1, "timeout_s": 2.0, "byte_order": "big",
              "word_order": "big", "discover_table": "hr", "discover_start": 0, "discover_count": 40}
MQTT_CFG = {"host": LAB_HOST, "port": MQTT_PORT, "topic_filter": "riverside/#", "qos": "1", "tls": False, "client_id": ""}

# Line 3 PLC register map (see tools/field_sim/plc.py)
CONVEYOR_POINTS = [_pm(f"hr:1:uint16:{STATE_MAP}", "state"), _pm("hr:2", "speed_mps", 0.01), _pm("hr:3:uint32", "item_count")]
CONVEYOR_CONTROLS = [_cm("start", "co:0", True), _cm("stop", "co:0", False), _cm("speed_setpoint", "hr:0", param="value", scale=100)]
MOTOR_POINTS = [_pm(f"hr:10:uint16:{STATE_MAP}", "state"), _pm("hr:11", "rpm"), _pm("hr:12", "current", 0.1),
                _pm("hr:13", "winding_temp", 0.1), _pm("hr:14", "vibration", 0.01)]
MOTOR_CONTROLS = [_cm("start", "co:0", True), _cm("stop", "co:0", False), _cm("speed_setpoint", "hr:0", param="value", scale=120 / 1450)]
PUMP_POINTS = [_pm(f"hr:20:uint16:{STATE_MAP}", "state"), _pm("hr:21", "flow", 0.1), _pm("hr:22", "discharge_pressure", 0.01)]
PUMP_CONTROLS = [_cm("start", "co:1", True), _cm("stop", "co:1", False)]
PANEL_POINTS = [_pm("hr:30:uint16:map=0=healthy;1=tripped", "estop_status"), _pm("hr:31", "cabinet_temp", 0.1)]

FIELD_DEVICES = [
    # (name, asset_code, protocol, config, points, controls)
    ("PLC-001 Line 3 · CV-301 conveyor (Modbus TCP)", "CV-301", "modbus_tcp", MODBUS_CFG, CONVEYOR_POINTS, CONVEYOR_CONTROLS),
    ("PLC-001 Line 3 · MTR-301 drive (Modbus TCP)", "MTR-301", "modbus_tcp", MODBUS_CFG, MOTOR_POINTS, MOTOR_CONTROLS),
    ("PLC-001 Line 3 · PMP-401 coolant pump (Modbus TCP)", "PMP-401", "modbus_tcp", MODBUS_CFG, PUMP_POINTS, PUMP_CONTROLS),
    ("PLC-001 · CP-001 E-stop circuit (Modbus TCP)", "CP-001", "modbus_tcp", MODBUS_CFG, PANEL_POINTS, []),
    ("TT-101 transmitter (MQTT)", "TT-101", "mqtt", MQTT_CFG, [_pm("riverside/hall-a/tt-101#temp", "temp")], []),
    ("TT-201 transmitter (MQTT)", "TT-201", "mqtt", MQTT_CFG, [_pm("riverside/hall-a/tt-201#temp", "temp")], []),
    ("EM-001 incomer meter (MQTT)", "EM-001", "mqtt", MQTT_CFG,
     [_pm("riverside/utilities/em-001#power_kw", "power_kw"), _pm("riverside/utilities/em-001#voltage", "voltage"),
      _pm("riverside/utilities/em-001#energy_kwh", "energy_kwh"), _pm("riverside/utilities/em-001#power_factor", "power_factor")], []),
    ("EM-002 Line 1 meter (MQTT)", "EM-002", "mqtt", MQTT_CFG,
     [_pm("riverside/hall-a/em-002#power_kw", "power_kw"), _pm("riverside/hall-a/em-002#voltage", "voltage")], []),
]
# Simulated devices now replaced by field devices (disabled if still at seeded config).
REPLACED = {"CV-301 simulator", "MTR-301 drive simulator", "PMP-401 simulator", "CP-001 panel simulator",
            "TT-101 simulator", "TT-201 simulator", "EM-001 simulator", "EM-002 simulator"}

SIM_CONVEYOR_CONTROLS = [_cm("start", "state", "running"), _cm("stop", "state", "stopped"),
                         _cm("speed_setpoint", "speed_mps", param="value")]
SIM_MOTOR_CONTROLS = [_cm("start", "state", "running"), _cm("stop", "state", "stopped"), _cm("speed_setpoint", "rpm", param="value")]
SIM_CONTROLS = {"CV-101 simulator": SIM_CONVEYOR_CONTROLS, "CV-102 simulator": SIM_CONVEYOR_CONTROLS,
                "CV-201 simulator": SIM_CONVEYOR_CONTROLS, "CV-302 simulator": SIM_CONVEYOR_CONTROLS,
                "MTR-101 drive simulator": SIM_MOTOR_CONTROLS, "MTR-102 drive simulator": SIM_MOTOR_CONTROLS,
                "MTR-201 drive simulator": SIM_MOTOR_CONTROLS}

# (asset, control, source asset, measurement, op, value, message)
INTERLOCKS = [
    ("CV-301", "start", "CP-001", "estop_status", "==", "healthy", "Plant E-stop circuit must be healthy (reset the physical E-stop first)."),
    ("CV-301", "start", "CV-302", "state", "==", "running", "Downstream palletizer conveyor CV-302 must be running to avoid a pile-up."),
    ("MTR-301", "start", "CP-001", "estop_status", "==", "healthy", "Plant E-stop circuit must be healthy."),
    ("PMP-401", "start", "TK-401", "level_pct", ">", "10", "Coolant tank level must be above 10 % (pump dry-run protection)."),
    ("PMP-401", "start", "CP-001", "estop_status", "==", "healthy", "Plant E-stop circuit must be healthy."),
]

# Control-definition upgrades (feedback, approval) merged into the demo asset types.
CONTROL_UPGRADES = {
    "conveyor": {
        "start": {"feedback_value": "running", "timeout_s": 12},
        "stop": {"feedback_value": "stopped", "timeout_s": 12},
        "speed_setpoint": {"min_role": "operator", "requires_approval": True, "feedback_tolerance": 0.05, "timeout_s": 15},
    },
    "motor": {
        "start": {"feedback_value": "running", "timeout_s": 12},
        "stop": {"feedback_value": "stopped", "timeout_s": 12},
        "speed_setpoint": {"min_role": "operator", "requires_approval": True, "feedback_tolerance": 30, "timeout_s": 15},
    },
    "pump": {"start": {"feedback_value": "running", "timeout_s": 12}, "stop": {"feedback_value": "stopped", "timeout_s": 12}},
    "valve": {"open": {"feedback_value": 100, "feedback_tolerance": 5}, "close": {"feedback_value": 0, "feedback_tolerance": 5}},
}

TEMPLATES = [
    {"key": "plc_conveyor_modbus", "name": "Line PLC conveyor (Modbus TCP)", "protocol": "modbus_tcp", "asset_type_key": "conveyor",
     "description": "Conveyor on a line PLC: run coil, speed setpoint (cm/s) and state/speed/count registers.",
     "connection_config": MODBUS_CFG, "point_mappings": CONVEYOR_POINTS, "control_mappings": CONVEYOR_CONTROLS},
    {"key": "plc_pump_modbus", "name": "Line PLC pump (Modbus TCP)", "protocol": "modbus_tcp", "asset_type_key": "pump",
     "description": "Pump on a line PLC: run coil, state, flow (×0.1) and pressure (×0.01).",
     "connection_config": MODBUS_CFG, "point_mappings": PUMP_POINTS, "control_mappings": PUMP_CONTROLS},
    {"key": "modbus_energy_meter_f32", "name": "Energy meter, float32 input registers (Modbus TCP)", "protocol": "modbus_tcp",
     "asset_type_key": "energy_meter",
     "description": "Typical 3-phase meter map. Adjust addresses to the meter's manual.",
     "connection_config": {**MODBUS_CFG, "port": 502, "discover_table": "ir"},
     "point_mappings": [_pm("ir:0:float32", "voltage"), _pm("ir:52:float32", "power_kw", 0.001),
                        _pm("ir:62:float32", "power_factor"), _pm("ir:342:float32", "energy_kwh")], "control_mappings": []},
    {"key": "mqtt_temperature_json", "name": "Temperature transmitter (MQTT JSON)", "protocol": "mqtt",
     "asset_type_key": "temperature_sensor",
     "description": 'Payload {"temp": 64.2, "ts": <epoch ms>, "seq": <n>}. Replace the topic with the device topic.',
     "connection_config": MQTT_CFG, "point_mappings": [_pm("site/area/tag#temp", "temp")], "control_mappings": []},
    {"key": "mqtt_energy_meter_json", "name": "Energy meter (MQTT JSON)", "protocol": "mqtt", "asset_type_key": "energy_meter",
     "description": "Payload with power_kw, voltage, energy_kwh, power_factor.",
     "connection_config": MQTT_CFG,
     "point_mappings": [_pm("site/area/meter#power_kw", "power_kw"), _pm("site/area/meter#voltage", "voltage"),
                        _pm("site/area/meter#energy_kwh", "energy_kwh"), _pm("site/area/meter#power_factor", "power_factor")],
     "control_mappings": []},
    {"key": "sim_conveyor", "name": "Simulated conveyor", "protocol": "simulated", "asset_type_key": "conveyor",
     "description": "Software conveyor with start/stop/speed control, for testing without hardware.",
     "connection_config": {"profile": "conveyor", "seed": 1, "fail_test": False},
     "point_mappings": [_pm("state", "state"), _pm("speed_mps", "speed_mps"), _pm("item_count", "item_count")],
     "control_mappings": SIM_CONVEYOR_CONTROLS},
]


def install_device_templates(db: Session, org_id: str) -> int:
    have = set(db.scalars(select(DeviceTemplate.key).where(DeviceTemplate.org_id == org_id)))
    n = 0
    for t in TEMPLATES:
        if t["key"] not in have:
            db.add(DeviceTemplate(org_id=org_id, builtin=True, **t))
            n += 1
    return n


# Values the seed shipped with; only these are replaced, so deliberate user edits survive.
SEED_DEFAULTS = {"feedback_value": None, "feedback_tolerance": None, "requires_approval": False, "timeout_s": 15.0, "min_role": "engineer"}


def _upgrade_controls(types: dict[str, AssetType]) -> list[str]:
    done = []
    for key, upgrades in CONTROL_UPGRADES.items():
        t = types.get(key)
        if t is None:
            continue
        new, changed = [], False
        for c in t.controls:
            patch = {k: v for k, v in upgrades.get(c["key"], {}).items()
                     if c.get(k, SEED_DEFAULTS.get(k)) == SEED_DEFAULTS.get(k) and c.get(k) != v}
            if patch:
                c = {**c, **patch}
                changed = True
            new.append(c)
        if changed:
            t.controls = new
            t.version += 1
            done.append(f"controls {key}")
    return done


def ensure_field_devices(db: Session) -> list[str]:
    done: list[str] = []
    for org in db.scalars(select(Organization)):
        if install_device_templates(db, org.id):
            done.append(f"templates for {org.slug}")
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_SLUG))
    from app.core.config import get_settings

    if org is None or not get_settings().demo_field_devices:
        if org is not None:
            types = {t.key: t for t in db.scalars(select(AssetType).where(AssetType.org_id == org.id))}
            done += _upgrade_controls(types)
            devs = {d.name: d for d in db.scalars(select(Device).where(Device.org_id == org.id))}
            for name, controls in SIM_CONTROLS.items():
                if name in devs and not devs[name].control_mappings:
                    devs[name].control_mappings = controls
        db.commit()
        return done
    factory = db.scalar(select(Factory).where(Factory.org_id == org.id).order_by(Factory.created_at))
    if factory is None:
        db.commit()
        return done
    assets = {a.code: a for a in db.scalars(select(Asset).where(Asset.factory_id == factory.id))}
    types = {t.key: t for t in db.scalars(select(AssetType).where(AssetType.org_id == org.id))}
    done += _upgrade_controls(types)

    devices = {d.name: d for d in db.scalars(select(Device).where(Device.factory_id == factory.id))}
    for name, code, proto, cfg, points, controls in FIELD_DEVICES:
        if name in devices or code not in assets:
            continue
        db.add(Device(org_id=org.id, factory_id=factory.id, asset_id=assets[code].id, name=name, protocol=proto,
                      connection_config=dict(cfg), point_mappings=points, control_mappings=controls, enabled=True))
        done.append(f"device {name}")
        for old in REPLACED:
            d = devices.get(old)
            if d is not None and d.asset_id == assets[code].id and d.enabled and d.protocol == "simulated":
                d.enabled = False
                d.name = f"{old} (replaced by field device)"
                done.append(f"disabled {old}")
    for name, controls in SIM_CONTROLS.items():
        d = devices.get(name)
        if d is not None and not d.control_mappings:
            d.control_mappings = controls
            done.append(f"controls on {name}")

    existing = {(i.asset_id, i.control_key, i.source_asset_id, i.measurement) for i in db.scalars(select(Interlock).where(Interlock.org_id == org.id))}
    for code, ctl, src, meas, op, val, msg in INTERLOCKS:
        if code in assets and src in assets and (assets[code].id, ctl, assets[src].id, meas) not in existing:
            db.add(Interlock(org_id=org.id, asset_id=assets[code].id, control_key=ctl, source_asset_id=assets[src].id,
                             measurement=meas, operator=op, value=val, message=msg))
            done.append(f"interlock {code}.{ctl}")
    if done:
        audit.record(db, None, "demo.upgrade", "organization", org.id, "Field integration: " + ", ".join(done[:5]) + ("…" if len(done) > 5 else ""), org_id=org.id)
    db.commit()
    return done
