"""Demonstration factory. Loaded on startup when SEED_DEMO=true and absent.

Everything here goes through the same models as user-created data: the demo is
an ordinary organization, not special-cased anywhere in the platform.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.core.security import hash_password
from app.models import Asset, AssetType, Device, Factory, FactoryFloor, Organization, ProductionArea, User
from app.seed.library import install_standard_library
from app.services import audit

DEMO_SLUG = "demo"
DEMO_PASSWORD = "demo1234"  # development only; documented in README
DEMO_USERS = [
    ("admin@demo.example.com", "Alex Admin", Role.ADMIN),
    ("engineer@demo.example.com", "Erin Engineer", Role.ENGINEER),
    ("operator@demo.example.com", "Omar Operator", Role.OPERATOR),
    ("viewer@demo.example.com", "Vic Viewer", Role.VIEWER),
]

# (code, name, type_key, area, parent_code, properties)
ASSETS = [
    ("LINE-1", "Line 1 – Machining", "production_line", "A", None, {"product": "Pump housing", "takt_time_s": 90}),
    ("LINE-2", "Line 2 – Assembly", "production_line", "A", None, {"product": "Pump assembly", "takt_time_s": 120}),
    ("LINE-3", "Line 3 – Packaging", "production_line", "B", None, {"product": "Boxed pump", "takt_time_s": 60}),
    ("CV-101", "Infeed conveyor L1", "conveyor", "A", "LINE-1", {"length_m": 8}),
    ("CV-102", "Transfer conveyor L1", "conveyor", "A", "LINE-1", {"length_m": 5}),
    ("MTR-101", "Infeed conveyor drive", "motor", "A", "CV-101", {"rated_power_kw": 5.5}),
    ("MTR-102", "Transfer conveyor drive", "motor", "A", "CV-102", {"rated_power_kw": 4}),
    ("TT-101", "Spindle coolant temperature", "temperature_sensor", "A", "LINE-1", {}),
    ("CV-201", "Assembly conveyor L2", "conveyor", "A", "LINE-2", {"length_m": 12}),
    ("MTR-201", "Assembly conveyor drive", "motor", "A", "CV-201", {"rated_power_kw": 7.5}),
    ("RBT-201", "Assembly robot", "robot_arm", "A", "LINE-2", {"payload_kg": 20, "reach_mm": 1800}),
    ("TT-201", "Assembly cell ambient", "temperature_sensor", "A", "LINE-2", {"range_max": 60}),
    ("CV-301", "Packing conveyor L3", "conveyor", "B", "LINE-3", {"length_m": 10}),
    ("CV-302", "Palletizer conveyor L3", "conveyor", "B", "LINE-3", {"length_m": 6}),
    ("MTR-301", "Packing conveyor drive", "motor", "B", "CV-301", {"rated_power_kw": 5.5}),
    ("TT-301", "Shrink tunnel temperature", "temperature_sensor", "B", "LINE-3", {"range_max": 250}),
    ("PMP-401", "Coolant pump", "pump", "U", None, {"rated_flow_m3h": 25}),
    ("TK-401", "Coolant tank", "tank", "U", None, {"capacity_m3": 15, "medium": "Water-glycol"}),
    ("PT-401", "Coolant header pressure", "pressure_sensor", "U", "PMP-401", {}),
    ("EM-001", "Main incomer energy meter", "energy_meter", "U", None, {"ct_ratio": "800/5"}),
    ("EM-002", "Line 1 sub-meter", "energy_meter", "A", "LINE-1", {}),
    ("CP-001", "Main control panel", "control_panel", "U", None, {}),
    ("PLC-001", "Line controller PLC", "plc", "U", "CP-001", {"vendor_family": "Generic", "ip_address": "10.10.1.10"}),
]

# (name, asset_code, profile, seed, mappings[(point, measurement)])
DEVICES = [
    ("TT-101 simulator", "TT-101", "temperature", 101, [("temp", "temp")]),
    ("TT-201 simulator", "TT-201", "temperature", 201, [("temp", "temp")]),
    ("TT-301 simulator", "TT-301", "temperature", 301, [("temp", "temp")]),
    ("PT-401 simulator", "PT-401", "pressure", 401, [("pressure", "pressure")]),
    ("MTR-101 drive simulator", "MTR-101", "motor", 11, [("rpm", "rpm"), ("current", "current"), ("winding_temp", "winding_temp"), ("vibration", "vibration")]),
    ("MTR-201 drive simulator", "MTR-201", "motor", 21, [("rpm", "rpm"), ("current", "current"), ("winding_temp", "winding_temp"), ("vibration", "vibration")]),
    ("EM-001 simulator", "EM-001", "energy", 1, [("power_kw", "power_kw"), ("voltage", "voltage"), ("energy_kwh", "energy_kwh")]),
    ("EM-002 simulator", "EM-002", "energy", 2, [("power_kw", "power_kw"), ("voltage", "voltage")]),
    ("TK-401 level simulator", "TK-401", "level", 4, [("level_pct", "level_pct")]),
]


def seed_demo(db: Session) -> bool:
    if db.scalar(select(Organization).where(Organization.slug == DEMO_SLUG)):
        return False
    org = Organization(name="Demo Manufacturing Co.", slug=DEMO_SLUG)
    db.add(org)
    db.flush()
    pw = hash_password(DEMO_PASSWORD)
    users = []
    for email, name, role in DEMO_USERS:
        u = User(org_id=org.id, email=email, name=name, password_hash=pw, role=role)
        db.add(u)
        users.append(u)
    install_standard_library(db, org.id)
    db.flush()

    f = Factory(
        org_id=org.id, name="Riverside Plant", location="Building 1, Riverside Industrial Estate",
        description="Demonstration plant: machining, assembly and packaging lines with shared utilities.",
    )
    db.add(f)
    db.flush()
    floor = FactoryFloor(org_id=org.id, factory_id=f.id, name="Ground floor", level=0, width_m=80, depth_m=40)
    db.add(floor)
    db.flush()
    areas = {
        "A": ProductionArea(org_id=org.id, floor_id=floor.id, name="Hall A – Machining & Assembly", kind="production", bounds={"x": 0, "z": 0, "width": 45, "depth": 40}),
        "B": ProductionArea(org_id=org.id, floor_id=floor.id, name="Hall B – Packaging", kind="production", bounds={"x": 45, "z": 0, "width": 35, "depth": 25}),
        "U": ProductionArea(org_id=org.id, floor_id=floor.id, name="Utilities", kind="utility", bounds={"x": 45, "z": 25, "width": 35, "depth": 15}),
    }
    db.add_all(areas.values())
    db.flush()

    types = {t.key: t for t in db.scalars(select(AssetType).where(AssetType.org_id == org.id))}
    by_code: dict[str, Asset] = {}
    from app.services.properties import validate_properties

    for code, name, tkey, area, parent, props in ASSETS:
        t = types[tkey]
        a = Asset(
            org_id=org.id, factory_id=f.id, area_id=areas[area].id,
            parent_id=by_code[parent].id if parent else None, asset_type_id=t.id,
            code=code, name=name, properties=validate_properties(t.property_schema, props),
        )
        db.add(a)
        db.flush()
        by_code[code] = a

    for name, code, profile, seed, maps in DEVICES:
        db.add(
            Device(
                org_id=org.id, factory_id=f.id, asset_id=by_code[code].id, name=name, protocol="simulated",
                connection_config={"profile": profile, "seed": seed, "fail_test": False},
                point_mappings=[{"point": p, "measurement": m, "scale": 1.0, "offset": 0.0} for p, m in maps],
                enabled=True,
            )
        )
    audit.record(db, None, "demo.seed", "organization", org.id, "Loaded demonstration factory", org_id=org.id)
    db.commit()
    return True
