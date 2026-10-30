from tests.conftest import type_by_key


def test_custom_type_without_code_changes(client, new_org, factory):
    h, _ = new_org(lib=False)
    body = {
        "key": "vibration_probe", "name": "Vibration probe", "category": "sensor",
        "property_schema": [{"key": "sensitivity", "label": "Sensitivity", "type": "number", "unit": "mV/g", "default": 100}],
        "telemetry": [{"key": "vrms", "label": "Velocity RMS", "unit": "mm/s", "alarm_high": 7.1}],
    }
    r = client.post("/api/asset-types", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert client.post("/api/asset-types", json=body, headers=h).status_code == 409
    f = factory(h)
    a = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": r.json()["id"], "code": "VP-1", "name": "Probe"}, headers=h)
    assert a.json()["properties"] == {"sensitivity": 100}


def test_definition_validation(client, new_org):
    h, _ = new_org(lib=False)
    base = {"key": "x", "name": "X", "category": "c"}
    bad = [
        {"property_schema": [{"key": "a", "label": "A", "type": "number"}, {"key": "a", "label": "B", "type": "number"}]},
        {"property_schema": [{"key": "e", "label": "E", "type": "enum"}]},
        {"property_schema": [{"key": "Bad Key", "label": "E", "type": "string"}]},
        {"telemetry": [{"key": "t", "label": "T", "expected_interval_s": 0}]},
        {"visual": {"color": "red"}},
    ]
    for extra in bad:
        assert client.post("/api/asset-types", json=base | extra, headers=h).status_code == 422, extra


def test_schema_change_keeps_assets_valid(client, new_org, factory):
    h, _ = new_org()
    f = factory(h)
    t = type_by_key(client, h, "tank")
    a = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": t["id"], "code": "TK", "name": "Tank"}, headers=h).json()
    assert a["properties"] == {"capacity_m3": 20, "medium": "Water"}

    # Adding a required property without default would orphan existing assets
    schema = t["property_schema"] + [{"key": "material", "label": "Material", "type": "string", "required": True}]
    r = client.patch(f"/api/asset-types/{t['id']}", json={"property_schema": schema}, headers=h)
    assert r.status_code == 409

    # With a default it is applied; removing 'medium' drops its value
    schema = [p for p in t["property_schema"] if p["key"] != "medium"] + [
        {"key": "material", "label": "Material", "type": "string", "required": True, "default": "SS304"}
    ]
    r = client.patch(f"/api/asset-types/{t['id']}", json={"property_schema": schema}, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 2
    a2 = client.get(f"/api/assets/{a['id']}", headers=h).json()
    assert a2["properties"] == {"capacity_m3": 20, "material": "SS304"}
    assert a2["version"] == 2
    assert client.delete(f"/api/asset-types/{t['id']}", headers=h).status_code == 409
