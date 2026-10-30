import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Device
from tests.conftest import type_by_key


@pytest.fixture
def ctx(client, new_org, factory):
    h, _ = new_org()
    f = factory(h)
    t = type_by_key(client, h, "temperature_sensor")
    a = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": t["id"], "code": "TT", "name": "T"}, headers=h).json()
    return h, f, a


def test_protocol_catalog(client, demo_admin):
    protos = {p["key"]: p for p in client.get("/api/protocols", headers=demo_admin).json()}
    assert protos["simulated"]["status"] == "available"
    assert protos["modbus_tcp"]["status"] == "planned"


def test_planned_or_unknown_protocol_rejected(client, ctx):
    h, f, _ = ctx
    for proto in ("modbus_tcp", "nonsense"):
        r = client.post("/api/devices", json={"factory_id": f["id"], "name": "d", "protocol": proto}, headers=h)
        assert r.status_code == 422


def test_config_validation(client, ctx):
    h, f, _ = ctx
    base = {"factory_id": f["id"], "name": "d", "protocol": "simulated"}
    assert client.post("/api/devices", json=base | {"connection_config": {"profile": "nope"}}, headers=h).status_code == 422
    assert client.post("/api/devices", json=base | {"connection_config": {"profile": "temperature", "extra": 1}}, headers=h).status_code == 422
    # Simulator declares no secret fields, so any credential is rejected
    r = client.post("/api/devices", json=base | {"connection_config": {"profile": "temperature"}, "credentials": {"password": "x"}}, headers=h)
    assert r.status_code == 422


def test_mapping_must_match_telemetry(client, ctx):
    h, f, a = ctx
    base = {"factory_id": f["id"], "name": "d", "protocol": "simulated", "asset_id": a["id"],
            "connection_config": {"profile": "temperature"}}
    r = client.post("/api/devices", json=base | {"point_mappings": [{"point": "temp", "measurement": "rpm"}]}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/devices", json=base | {"point_mappings": [{"point": "temp", "measurement": "temp"}]}, headers=h)
    assert r.status_code == 201


def test_test_connection_and_discovery(client, ctx):
    h, f, a = ctx
    d = client.post("/api/devices", json={"factory_id": f["id"], "name": "d", "protocol": "simulated",
                                          "connection_config": {"profile": "motor"}}, headers=h).json()
    assert d["last_test_status"] == "unknown"
    r = client.post(f"/api/devices/{d['id']}/test", headers=h).json()
    assert r["ok"] is True
    pts = client.post(f"/api/devices/{d['id']}/discover", headers=h).json()
    assert {p["point"] for p in pts} == {"rpm", "current", "winding_temp", "vibration"}

    client.patch(f"/api/devices/{d['id']}", json={"connection_config": {"profile": "motor", "fail_test": True}}, headers=h)
    assert client.get(f"/api/devices/{d['id']}", headers=h).json()["last_test_status"] == "unknown"
    r = client.post(f"/api/devices/{d['id']}/test", headers=h).json()
    assert r["ok"] is False
    assert client.get(f"/api/devices/{d['id']}", headers=h).json()["last_test_status"] == "error"


def test_credentials_are_write_only_and_encrypted(client, ctx, monkeypatch):
    from app.adapters.simulated import SimulatedAdapter
    from app.schemas.devices import ConfigField

    monkeypatch.setattr(SimulatedAdapter, "config_schema",
                        SimulatedAdapter.config_schema + [ConfigField(key="password", label="Password", type="string", secret=True)])
    h, f, _ = ctx
    r = client.post("/api/devices", json={"factory_id": f["id"], "name": "secure", "protocol": "simulated",
                                          "connection_config": {"profile": "temperature"},
                                          "credentials": {"password": "s3cret-value"}}, headers=h)
    assert r.status_code == 201, r.text
    body = r.text + client.get(f"/api/devices/{r.json()['id']}", headers=h).text + client.get("/api/audit", headers=h).text
    assert "s3cret-value" not in body
    assert r.json()["has_credentials"] is True
    with SessionLocal() as db:
        stored = db.scalar(select(Device).where(Device.id == r.json()["id"])).credentials_encrypted
    assert stored and "s3cret-value" not in stored
