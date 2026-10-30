import pytest

from app.services.properties import PropertyValidationError, validate_properties
from tests.conftest import type_by_key

SCHEMA = [
    {"key": "power", "label": "Power", "type": "number", "min": 0, "max": 100, "required": True, "default": 5},
    {"key": "poles", "label": "Poles", "type": "integer"},
    {"key": "drive", "label": "Drive", "type": "enum", "options": ["DOL", "VFD"]},
    {"key": "ok", "label": "OK", "type": "boolean"},
]


def test_property_validation_unit():
    assert validate_properties(SCHEMA, {}) == {"power": 5}
    assert validate_properties(SCHEMA, {"power": 10, "poles": 4.0, "ok": False}) == {"power": 10, "poles": 4, "ok": False}
    cases = [{"power": 101}, {"power": "x"}, {"power": True}, {"poles": 2.5}, {"drive": "star"},
             {"ok": "yes"}, {"nope": 1}, {"power": None}]
    for bad in cases:
        with pytest.raises(PropertyValidationError):
            validate_properties(SCHEMA, bad)


@pytest.fixture
def setup(client, new_org, factory):
    h, _ = new_org()
    f = factory(h)
    motor = type_by_key(client, h, "motor")
    return h, f, motor


def mk(client, h, f, t, **kw):
    body = {"factory_id": f["id"], "asset_type_id": t["id"], "code": "M-1", "name": "Motor"} | kw
    return client.post("/api/assets", json=body, headers=h)


def test_create_applies_defaults_and_validates(client, setup):
    h, f, motor = setup
    r = mk(client, h, f, motor)
    assert r.status_code == 201
    assert r.json()["properties"]["rated_power_kw"] == 7.5
    r = mk(client, h, f, motor, code="M-2", properties={"rated_power_kw": -1, "bogus": 1})
    assert r.status_code == 422
    assert set(r.json()["detail"]["fields"]) == {"rated_power_kw", "bogus"}
    assert mk(client, h, f, motor).status_code == 409  # duplicate code


def test_update_versioning_and_audit(client, setup):
    h, f, motor = setup
    a = mk(client, h, f, motor).json()
    r = client.patch(f"/api/assets/{a['id']}", json={"version": 1, "name": "Renamed"}, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 2
    r = client.patch(f"/api/assets/{a['id']}", json={"version": 1, "name": "Stale"}, headers=h)
    assert r.status_code == 409
    log = client.get(f"/api/audit?entity_id={a['id']}", headers=h).json()
    assert [e["action"] for e in log] == ["asset.update", "asset.create"]
    assert log[0]["details"]["name"] == {"from": "Motor", "to": "Renamed"}


def test_parent_cycle_rejected(client, setup):
    h, f, motor = setup
    a = mk(client, h, f, motor, code="A").json()
    b = mk(client, h, f, motor, code="B", parent_id=a["id"]).json()
    r = client.patch(f"/api/assets/{a['id']}", json={"parent_id": b["id"]}, headers=h)
    assert r.status_code == 422
    r = client.patch(f"/api/assets/{a['id']}", json={"parent_id": a["id"]}, headers=h)
    assert r.status_code == 422


def test_area_must_belong_to_factory(client, setup, factory):
    h, f, motor = setup
    other = factory(h, "Other")
    floor = client.post(f"/api/factories/{other['id']}/floors", json={"name": "G"}, headers=h).json()
    area = client.post(f"/api/floors/{floor['id']}/areas", json={"name": "Z"}, headers=h).json()
    assert mk(client, h, f, motor, area_id=area["id"]).status_code == 422
    assert mk(client, h, other, motor, area_id=area["id"]).status_code == 201
    # area with assets cannot be deleted
    assert client.delete(f"/api/areas/{area['id']}", headers=h).status_code == 409


def test_search_and_filters(client, demo_admin):
    r = client.get("/api/assets?q=conveyor", headers=demo_admin).json()
    assert r and all("onveyor" in a["name"] for a in r)
    sensors = client.get("/api/assets?category=sensor", headers=demo_admin).json()
    assert {a["asset_type"]["category"] for a in sensors} == {"sensor"}
