"""Demo factory layout, extra simulated devices and default dashboard.

Idempotent: safe to run on every start. Only adds what is missing, and only
updates demo devices whose configuration is still exactly as originally seeded.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, AssetType, Dashboard, Device, Factory, FactoryFloor, Organization, Scene, SceneObject, SceneVersion
from app.seed.demo import DEMO_SLUG
from app.services import audit

# ---- devices: (name, asset_code, profile, seed, [(point, measurement)]) ----
MOTOR = [("state", "state"), ("rpm", "rpm"), ("current", "current"), ("winding_temp", "winding_temp"), ("vibration", "vibration")]
CONV = [("state", "state"), ("speed_mps", "speed_mps"), ("item_count", "item_count")]
DEVICES = [
    ("TT-101 simulator", "TT-101", "temperature", 101, [("temp", "temp")]),
    ("TT-201 simulator", "TT-201", "temperature", 201, [("temp", "temp")]),
    ("TT-301 simulator", "TT-301", "temperature_hot", 301, [("temp", "temp")]),
    ("PT-401 simulator", "PT-401", "pressure", 401, [("pressure", "pressure")]),
    ("MTR-101 drive simulator", "MTR-101", "motor", 11, MOTOR),
    ("MTR-102 drive simulator", "MTR-102", "motor", 12, MOTOR),
    ("MTR-201 drive simulator", "MTR-201", "motor", 21, MOTOR),
    ("MTR-301 drive simulator", "MTR-301", "motor_intermittent", 31, MOTOR),
    ("CV-101 simulator", "CV-101", "conveyor", 11, CONV),
    ("CV-102 simulator", "CV-102", "conveyor", 12, CONV),
    ("CV-201 simulator", "CV-201", "conveyor", 21, CONV),
    ("CV-301 simulator", "CV-301", "conveyor_intermittent", 31, CONV),
    ("CV-302 simulator", "CV-302", "conveyor", 32, CONV),
    ("LINE-1 simulator", "LINE-1", "line", 1, [("state", "state"), ("output_count", "output_count")]),
    ("LINE-2 simulator", "LINE-2", "line", 2, [("state", "state"), ("output_count", "output_count")]),
    ("LINE-3 simulator", "LINE-3", "line", 3, [("state", "state"), ("output_count", "output_count")]),
    ("RBT-201 controller simulator", "RBT-201", "robot", 201,
     [("state", "state"), ("program", "program"), ("cycle_count", "cycle_count"), ("cycle_time_s", "cycle_time_s"), ("error_code", "error_code")]),
    ("PMP-401 simulator", "PMP-401", "pump", 401, [("state", "state"), ("flow", "flow"), ("discharge_pressure", "discharge_pressure")]),
    ("TK-401 level simulator", "TK-401", "level", 4, [("level_pct", "level_pct"), ("temp", "temp")]),
    ("EM-001 simulator", "EM-001", "energy", 1, [("power_kw", "power_kw"), ("voltage", "voltage"), ("energy_kwh", "energy_kwh"), ("power_factor", "power_factor")]),
    ("EM-002 simulator", "EM-002", "energy", 2, [("power_kw", "power_kw"), ("voltage", "voltage")]),
    ("CP-001 panel simulator", "CP-001", "panel", 1, [("estop_status", "estop_status"), ("cabinet_temp", "cabinet_temp")]),
    ("PLC-001 simulator", "PLC-001", "plc", 1, [("run_mode", "run_mode"), ("scan_time_ms", "scan_time_ms")]),
]
# Configurations from the Phase 1 seed; only these are upgraded automatically.
PHASE1_CONFIGS = {
    "TT-301 simulator": {"profile": "temperature", "seed": 301, "fail_test": False},
    "MTR-101 drive simulator": {"profile": "motor", "seed": 11, "fail_test": False},
    "MTR-201 drive simulator": {"profile": "motor", "seed": 21, "fail_test": False},
    "EM-001 simulator": {"profile": "energy", "seed": 1, "fail_test": False},
    "TK-401 level simulator": {"profile": "level", "seed": 4, "fail_test": False},
}

# ---- layout. Floor spans x 0..80, z 0..40 (metres). y is up. ----
# (asset_code, x, z, rotation_y_deg, size override or None)
PLACEMENTS = [
    ("LINE-1", 21, 8, 0, (36, 0.04, 6)),
    ("LINE-2", 21, 29, 0, (36, 0.04, 7)),
    ("LINE-3", 62.5, 11, 0, (31, 0.04, 6)),
    ("CV-101", 9, 8, 0, (8, 0.9, 0.8)),
    ("CV-102", 19.5, 8, 0, (5, 0.9, 0.8)),
    ("MTR-101", 4.5, 9.1, 0, None),
    ("MTR-102", 17.2, 9.1, 0, None),
    ("TT-101", 30, 9.6, 0, None),
    ("EM-002", 1, 4, 90, None),
    ("CV-201", 14, 28, 0, (12, 0.9, 0.8)),
    ("MTR-201", 7.5, 29.1, 0, None),
    ("RBT-201", 24, 30.6, 0, None),
    ("TT-201", 33, 25.4, 0, None),
    ("CV-301", 56, 11, 0, (10, 0.9, 0.8)),
    ("CV-302", 69, 11, 0, (6, 0.9, 0.8)),
    ("MTR-301", 50.5, 12.1, 0, None),
    ("TT-301", 73, 12.6, 0, None),
    ("TK-401", 51, 33, 0, None),
    ("PMP-401", 55.5, 33, 0, None),
    ("PT-401", 57.2, 33.4, 0, None),
    ("CP-001", 75, 39.3, 180, None),
    ("PLC-001", 73.3, 39.6, 180, None),
    ("EM-001", 77.2, 39.6, 180, None),
]
# (kind, name, shape, x, y_base, z, size, color, rot_y_deg, opacity). Positions are the centre of the
# object's base, so y is the height of its underside.
STRUCTURE = [
    ("wall", "North wall", "box", 40, 0, -0.15, (80.6, 6, 0.3), "#9aa4b2", 0, 1),
    ("wall", "South wall (west)", "box", 18.5, 0, 40.15, (37.6, 6, 0.3), "#9aa4b2", 0, 1),
    ("wall", "South wall (east)", "box", 61.5, 0, 40.15, (37.6, 6, 0.3), "#9aa4b2", 0, 1),
    ("door", "Loading door", "box", 40, 0, 40.15, (5, 5, 0.35), "#f59e0b", 0, 1),
    ("wall", "West wall", "box", -0.15, 0, 20, (0.3, 6, 40), "#9aa4b2", 0, 1),
    ("wall", "East wall", "box", 80.15, 0, 20, (0.3, 6, 40), "#9aa4b2", 0, 1),
    ("wall", "Hall A/B wall (north)", "box", 45, 0, 5.5, (0.25, 6, 11), "#8a94a3", 0, 1),
    ("wall", "Hall A/B wall (south)", "box", 45, 0, 28, (0.25, 6, 24), "#8a94a3", 0, 1),
    ("door", "Hall A/B passage", "box", 45, 0, 13, (0.3, 3.5, 4), "#64748b", 0, 0.35),
    ("wall", "Packaging/Utilities wall", "box", 58, 0, 25, (26, 6, 0.25), "#8a94a3", 0, 1),
    ("door", "Utilities door", "box", 75, 0, 25, (2, 2.5, 0.3), "#64748b", 0, 0.35),
    ("window", "North window 1", "box", 12, 3.25, -0.15, (6, 1.5, 0.36), "#7dd3fc", 0, 0.5),
    ("window", "North window 2", "box", 28, 3.25, -0.15, (6, 1.5, 0.36), "#7dd3fc", 0, 0.5),
    ("window", "North window 3", "box", 62, 3.25, -0.15, (6, 1.5, 0.36), "#7dd3fc", 0, 0.5),
    ("walkway", "Main aisle Hall A", "walkway", 22.5, 0.005, 18.5, (44, 0.02, 3), "#facc15", 0, 0.5),
    ("walkway", "Hall B aisle", "walkway", 62.5, 0.005, 17.5, (34, 0.02, 2.5), "#facc15", 0, 0.5),
    ("safety_zone", "Robot cell guarding", "zone", 24, 0.01, 30.6, (5, 0.04, 5), "#ef4444", 0, 0.35),
    ("workstation", "Assembly bench 1", "box", 33, 0, 32, (2, 0.9, 1), "#a3a3a3", 0, 1),
    ("workstation", "Assembly bench 2", "box", 37, 0, 32, (2, 0.9, 1), "#a3a3a3", 0, 1),
    ("storage", "Pallet rack 1", "box", 54, 0, 22.6, (6, 3, 1.1), "#3b82f6", 0, 1),
    ("storage", "Pallet rack 2", "box", 62, 0, 22.6, (6, 3, 1.1), "#3b82f6", 0, 1),
    ("storage", "Pallet rack 3", "box", 70, 0, 22.6, (6, 3, 1.1), "#3b82f6", 0, 1),
]
PILLARS = [(x, z) for x in (15, 30) for z in (14, 23)] + [(62, 5), (62, 30)]


def _rad(deg: float) -> float:
    return round(deg * 3.141592653589793 / 180, 6)


def build_layout(org_id: str, floor_id: str, assets: dict[str, Asset], types: dict[str, AssetType]) -> list[dict]:
    objs: list[dict] = []

    def add(**kw):
        base = {"id": str(uuid.uuid4()), "asset_id": None, "rotation": [0, 0, 0], "scale": [1, 1, 1], "opacity": 1.0,
                "model_id": None, "floor_id": floor_id, "group_id": None, "locked": False, "hidden": False,
                "sort": len(objs), "props": {}}
        base.update(kw)
        objs.append(base)

    for kind, name, shape, x, y, z, size, color, rot, op in STRUCTURE:
        add(kind=kind, name=name, shape=shape, position=[x, y, z], size=list(size), color=color,
            rotation=[0, _rad(rot), 0], opacity=op, locked=kind == "wall")
    for i, (x, z) in enumerate(PILLARS, 1):
        add(kind="pillar", name=f"Column C{i}", shape="cylinder", position=[x, 0, z], size=[0.5, 6, 0.5], color="#b8c0cc", locked=True)
    for code, x, z, rot, size in PLACEMENTS:
        a = assets.get(code)
        if a is None:
            continue
        v = types[a.asset_type_id].visual
        sz = list(size or v.get("size", [1, 1, 1]))
        add(kind="asset", asset_id=a.id, name=a.name, shape=v.get("shape", "box"), position=[x, 0, z],
            size=sz, color=v.get("color", "#6b7a90"), rotation=[0, _rad(rot), 0])
    return objs


def default_widgets(assets: dict[str, Asset]) -> list[dict]:
    def w(i, type_, title, size="s", code=None, m=None, minutes=30):
        return {"id": f"w{i}", "type": type_, "title": title, "size": size,
                "asset_id": assets[code].id if code in assets else None, "measurement": m, "minutes": minutes}

    return [
        w(1, "kpis", "Plant status", "w"),
        w(2, "trend", "Main incomer power", "l", "EM-001", "power_kw", 30),
        w(3, "alarms", "Limit violations", "m"),
        w(4, "gauge", "Infeed drive speed", "s", "MTR-101", "rpm"),
        w(5, "value", "Spindle coolant", "s", "TT-101", "temp"),
        w(6, "state", "Packing conveyor", "s", "CV-301", "state"),
        w(7, "value", "Robot cycles", "s", "RBT-201", "cycle_count"),
        w(8, "trend", "Shrink tunnel temperature", "l", "TT-301", "temp", 30),
        w(9, "gauge", "Coolant tank level", "s", "TK-401", "level_pct"),
        w(10, "value", "Header pressure", "s", "PT-401", "pressure"),
        w(11, "devices", "Data sources", "m"),
    ]


def ensure_demo_extras(db: Session) -> list[str]:
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_SLUG))
    if org is None:
        return []
    factory = db.scalar(select(Factory).where(Factory.org_id == org.id).order_by(Factory.created_at))
    if factory is None:
        return []
    done: list[str] = []
    assets = {a.code: a for a in db.scalars(select(Asset).where(Asset.factory_id == factory.id))}
    types = {t.id: t for t in db.scalars(select(AssetType).where(AssetType.org_id == org.id))}

    existing = {d.name: d for d in db.scalars(select(Device).where(Device.factory_id == factory.id))}
    for name, code, profile, seed, maps in DEVICES:
        cfg = {"profile": profile, "seed": seed, "fail_test": False}
        mappings = [{"point": p, "measurement": m, "scale": 1.0, "offset": 0.0} for p, m in maps]
        d = existing.get(name)
        # A device may have been renamed (e.g. "… (replaced by field device)") or the asset may now be
        # served by a real field device; never re-create a simulator in either case.
        renamed = any(n.startswith(name) for n in existing)
        field_served = code in assets and any(x.asset_id == assets[code].id and x.protocol != "simulated" for x in existing.values())
        if d is None and code in assets and not renamed and not field_served:
            db.add(Device(org_id=org.id, factory_id=factory.id, asset_id=assets[code].id, name=name, protocol="simulated",
                          connection_config=cfg, point_mappings=mappings, enabled=True))
            done.append(f"device {name}")
        elif d is not None and PHASE1_CONFIGS.get(name) == d.connection_config and (d.connection_config, d.point_mappings) != (cfg, mappings):
            d.connection_config = cfg
            d.point_mappings = mappings
            done.append(f"upgraded {name}")

    scene = db.scalar(select(Scene).where(Scene.factory_id == factory.id))
    if scene is None or scene.version == 0:
        if scene is None:
            scene = Scene(org_id=org.id, factory_id=factory.id, name=f"{factory.name} layout")
            db.add(scene)
            db.flush()
        floor = db.scalar(select(FactoryFloor).where(FactoryFloor.factory_id == factory.id).order_by(FactoryFloor.level))
        objs = build_layout(org.id, floor.id if floor else None, assets, types)
        db.add_all(SceneObject(org_id=org.id, scene_id=scene.id, **o) for o in objs)
        scene.version = 1
        scene.updated_by = "system"
        db.add(SceneVersion(org_id=org.id, scene_id=scene.id, version=1, message="Demo layout",
                            created_by="system", object_count=len(objs), snapshot=objs))
        done.append(f"layout ({len(objs)} objects)")

    if not db.scalar(select(Dashboard.id).where(Dashboard.factory_id == factory.id)):
        db.add(Dashboard(org_id=org.id, factory_id=factory.id, name="Plant overview",
                         widgets=default_widgets(assets), created_by="system"))
        done.append("dashboard")

    if done:
        audit.record(db, None, "demo.upgrade", "organization", org.id, "Demo content: " + ", ".join(done[:6]) + ("…" if len(done) > 6 else ""), org_id=org.id)
        db.commit()
    return done
